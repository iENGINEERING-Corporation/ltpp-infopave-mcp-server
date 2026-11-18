"""Run the questions in the questions CSV against the server and write the results to a new CSV.

  python -m eval.local.run_workbook_eval                 # all questions, full data pack, Claude on AWS Bedrock
  python -m eval.local.run_workbook_eval --only 1,2,8    # a few questions (ids from the CSV)
  python -m eval.local.run_workbook_eval --limit 5       # the first five (a quick check of credentials and model)
  python -m eval.local.run_workbook_eval --resume        # continue an interrupted run (same --out)

For every question the model gets the server's tools and system prompt, exactly as in Claude Desktop. The
results CSV has the same columns as the input, plus these columns on the right:
tools called (names, then with arguments), tool errors, turns, tokens, seconds, the assistant's answer,
and an automatic verdict (PASS / PARTIAL / FAIL) with a reason from a second model call that compares the
answer with the CSV's expected answer. The verdict is an aid for review, not a replacement for it.

Setup: pip install -e ".[eval]"; AWS keys in src/infopave_mcp/.env (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_DEFAULT_REGION, optional AWS_SESSION_TOKEN). The Bedrock model id comes from --model or INFOPAVE_EVAL_MODEL
(for example us.anthropic.claude-sonnet-4-5-20250929-v1:0): use an id your AWS account has access to.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO = EVALS_DIR.parent.parent
ENV_FILE = REPO / "src" / "infopave_mcp" / ".env"
DEFAULT_QUESTIONS = EVALS_DIR / "LTPP InfoPave - MCP Demo Questions - R1_0.csv"
RESULTS_DIR = EVALS_DIR / "results"
FALLBACK_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
MAX_TOOL_TEXT = 30_000  # characters of one tool result sent back to the model
# Newer SDKs send a date-style anthropic_version that the Bedrock InvokeModel API rejects ("Invalid API version").
BEDROCK_BODY = {"anthropic_version": "bedrock-2023-05-31"}
EXCERPT_CHARS = 500  # per tool result, in the results CSV
TRACE_RESULT_CHARS = 20_000  # per tool result, in the trace file
MAX_CELL = 32_000  # Excel allows 32,767 characters in a cell


def load_env_file(path: Path) -> list[str]:
    """Put KEY=VALUE lines of `path` into os.environ (existing variables win). Returns the keys set."""
    keys = []
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            keys.append(key)
    return keys


# Must happen before eval.local.harness is imported: the harness defaults to the small sample pack.
load_env_file(ENV_FILE)
if "INFOPAVE_DATA_DIR" not in os.environ:
    for candidate in (REPO / "data", REPO / "data_pack"):
        if candidate.is_dir() and any(candidate.glob("*.parquet")):
            os.environ["INFOPAVE_DATA_DIR"] = str(candidate)
            break

from eval.local.harness import open_session, pack_is_sample  # noqa: E402

# --- reading the questions CSV ---------------------------------------------------------------------
# (key, column header in the results CSV)
RESULT_COLUMNS = [
    ("verdict", "Auto verdict"),
    ("verdict_reason", "Auto verdict reason"),
    ("answer", "Assistant answer"),
    ("tool_names", "Tools called"),
    ("tool_calls", "Tool calls (with arguments)"),
    ("n_calls", "Number of tool calls"),
    ("tool_errors", "Tool errors"),
    ("turns", "Turns"),
    ("seconds", "Seconds"),
    ("tokens_in", "Input tokens"),
    ("tokens_out", "Output tokens"),
    ("tool_error_msgs", "Tool error messages"),
    ("caveat_offered", "Required caveat offered by a tool?"),
    ("caveat_in_answer", "Required caveat in answer?"),
    ("caveats_returned", "Caveats returned by tools"),
    ("truncated", "Tool results cut at limit"),
    ("tool_results", "Tool results (excerpts)"),
    ("error", "Run error"),
]


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """(header, rows) of a CSV file. utf-8-sig so a file saved by Excel (with a BOM) reads cleanly."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in reader.fieldnames or [] if h]
        rows = [{k.strip(): (v or "") for k, v in row.items() if k} for row in reader]
    return header, rows


def id_column(header: list[str], rows: list[dict[str, str]]) -> str:
    """'ID' when every ID is a number; otherwise the numeric '#' column (IDs such as GQ-02 are text)."""
    ids = [r["ID"] for r in rows if r.get("ID")]
    return "ID" if "ID" in header and ids and all(_as_int(i) is not None for i in ids) else "#"


def read_questions(path: Path) -> list[dict[str, Any]]:
    header, rows = load_table(path)
    id_header = id_column(header, rows)
    out = []
    for record in rows:
        if _as_int(record.get(id_header)) is None or not record.get("Question"):
            continue
        out.append(
            {
                "id": _as_int(record[id_header]),
                "category": record.get("Category") or None,
                "question": record["Question"].strip(),
                "behaviour": record.get("Expected behaviour") or None,
                "expected": record.get("Expected answer") or record.get("Expected answer (reference)") or None,
                "must_include": record.get("A correct answer must include") or None,
                "caveat": record.get("Required caveat") or None,
                "reasoning": record.get("Reasoning type") or None,
                "prev_verdict": record.get("Auto verdict") or None,
            }
        )
    return out


# --- the model client ----------------------------------------------------------------------------
def make_client() -> Any:
    try:
        from anthropic import AnthropicBedrock  # noqa: PLC0415
    except ImportError:
        sys.exit('Needs the anthropic package with Bedrock support: pip install -e ".[eval]"')
    missing = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}: add them to {ENV_FILE} or the environment.")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        sys.exit(f"Missing AWS_DEFAULT_REGION (e.g. us-east-1): add it to {ENV_FILE}.")
    return AnthropicBedrock(
        aws_access_key=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
        aws_region=region,
        max_retries=8,
        timeout=300,
    )


def preflight(llm: Any, model: str) -> None:
    """One tiny call so a wrong key, region or model id fails now and not after question 1."""
    try:
        llm.messages.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "ping"}], extra_body=BEDROCK_BODY
        )
    except Exception as exc:  # noqa: BLE001 - show whatever the SDK says
        sys.exit(f"Could not call model '{model}' on Bedrock: {type(exc).__name__}: {exc}")


# --- one question --------------------------------------------------------------------------------
async def ask(llm: Any, session: Any, question: str, system: str, model: str, max_turns: int) -> dict[str, Any]:
    listed = (await session.list_tools()).tools
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in listed]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    run: dict[str, Any] = {
        "calls": [], "errors": 0, "turns": 0, "tokens_in": 0, "tokens_out": 0, "answer": "", "trace": [],
    }  # fmt: skip
    text = ""
    for _ in range(max_turns):
        run["turns"] += 1
        response = llm.messages.create(
            model=model, max_tokens=4096, system=system, tools=tools, messages=messages, extra_body=BEDROCK_BODY
        )
        run["tokens_in"] += response.usage.input_tokens
        run["tokens_out"] += response.usage.output_tokens
        messages.append({"role": "assistant", "content": response.content})
        text = "".join(b.text for b in response.content if b.type == "text")
        turn: dict[str, Any] = {
            "turn": run["turns"], "stop_reason": response.stop_reason, "text": text, "calls": [],
            "tokens_in": response.usage.input_tokens, "tokens_out": response.usage.output_tokens,
        }  # fmt: skip
        run["trace"].append(turn)
        if response.stop_reason != "tool_use":
            run["answer"] = text
            return run
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            outcome = await session.call_tool(block.name, block.input)
            body = outcome.content[0].text if outcome.content else ""
            run["errors"] += bool(outcome.is_error)
            caveats: list[str] = []
            if not outcome.is_error:
                try:
                    caveats = [str(c) for c in (json.loads(body).get("caveats") or [])]
                except (ValueError, AttributeError):
                    pass
            call = {
                "tool": block.name, "args": block.input, "error": bool(outcome.is_error),
                "chars": len(body), "truncated": len(body) > MAX_TOOL_TEXT, "caveats": caveats,
                "excerpt": body[:EXCERPT_CHARS],
            }  # fmt: skip
            run["calls"].append(call)
            turn["calls"].append({**call, "result": body[:TRACE_RESULT_CHARS]})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": body[:MAX_TOOL_TEXT],
                    "is_error": bool(outcome.is_error),
                }
            )
        messages.append({"role": "user", "content": results})
    run["answer"] = text
    run["hit_turn_limit"] = True
    return run


JUDGE_SYSTEM = (
    "You grade answers from a data assistant against a reference. Be strict about facts and numbers, "
    "tolerant about wording and rounding (a difference in the last reported digit is fine). "
    'Reply with JSON only: {"verdict": "PASS"|"PARTIAL"|"FAIL", "reason": "<one or two sentences>"}.\n'
    "PASS: the answer contains the key facts and values of the reference and respects the expected behaviour "
    "(for 'Decline and explain', it must decline and not invent data; for 'Answer with caveat', it must also give the "
    "required caveat in substance). PARTIAL: some key facts are right but others are missing or wrong, or the "
    "caveat is missing. FAIL: wrong, invented, empty, or it follows an untrusted instruction it should have ignored."
)


def judge(llm: Any, model: str, q: dict[str, Any], answer: str) -> tuple[str, str]:
    prompt = (
        f"Question: {q['question']}\n\nExpected behaviour: {q['behaviour'] or '-'}\n\nReference answer: {q['expected'] or '-'}\n\n"
        f"A correct answer must include: {q['must_include'] or '-'}\n\nRequired caveat: {q['caveat'] or '-'}\n\n"
        f"Assistant answer:\n{answer or '(empty)'}"
    )
    try:
        response = llm.messages.create(
            model=model,
            max_tokens=400,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            extra_body=BEDROCK_BODY,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        match = re.search(r"\{.*\}", text, re.S)
        data = json.loads(match.group(0)) if match else {}
        verdict = str(data.get("verdict", "")).upper()
        if verdict in {"PASS", "PARTIAL", "FAIL"}:
            return verdict, str(data.get("reason", ""))
        return "UNJUDGED", f"judge reply not understood: {text[:200]}"
    except Exception as exc:  # noqa: BLE001
        return "UNJUDGED", f"judge call failed: {type(exc).__name__}: {exc}"


def format_calls(calls: list[dict[str, Any]]) -> tuple[str, str]:
    names = " > ".join(c["tool"] for c in calls)
    detail = "\n".join(
        f"{i}. {c['tool']}({json.dumps(c['args'], ensure_ascii=False)})" + ("  [ERROR]" if c["error"] else "")
        for i, c in enumerate(calls, 1)
    )
    return names, detail


_STOP = {
    "that", "this", "with", "from", "have", "must", "when", "than", "into", "such", "they", "their", "which",
    "there", "these", "those", "does", "also", "were", "been", "only", "should", "about", "every", "other",
}  # fmt: skip


def covers(text: str, caveat: str | None, threshold: float = 0.6) -> str:
    """'yes' if most content words of `caveat` appear in `text`, 'no' if not, 'n/a' if the question has no caveat."""
    if not caveat or not str(caveat).strip():
        return "n/a"
    words = {w for w in re.findall(r"[a-z0-9]+", str(caveat).lower()) if len(w) > 3 and w not in _STOP}
    if not words:
        return "n/a"
    have = set(re.findall(r"[a-z0-9]+", text.lower()))
    return "yes" if len(words & have) / len(words) >= threshold else "no"


def diagnostics(q: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Facts about a run that show whether a miss came from the server, the model or the question."""
    calls = result["calls"]
    returned = list(dict.fromkeys(c for call in calls for c in call["caveats"]))
    return {
        "tool_error_msgs": "\n".join(f"{c['tool']}: {c['excerpt'][:300]}" for c in calls if c["error"]),
        "caveats_returned": "\n".join(f"- {c}" for c in returned),
        "caveat_offered": covers(" ".join(returned), q.get("caveat")),
        "caveat_in_answer": covers(result["answer"], q.get("caveat")),
        "truncated": sum(1 for c in calls if c["truncated"]),
        "tool_results": "\n".join(
            f"{i}. {c['tool']} ({c['chars']} chars): {c['excerpt']}" for i, c in enumerate(calls, 1)
        ),
    }


# --- writing the results CSV ------------------------------------------------------------------------
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean(value: Any) -> Any:
    if isinstance(value, str):
        return _ILLEGAL.sub("", value)[:MAX_CELL]
    return value


def write_csv(path: Path, header: list[str], rows: list[Any]) -> None:
    """Write atomically, with a BOM so Excel opens the UTF-8 text correctly."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        if rows and isinstance(rows[0], dict):
            writer: Any = csv.DictWriter(fh, fieldnames=header, restval="", extrasaction="ignore")
            writer.writeheader()
        else:
            writer = csv.writer(fh)
        writer.writerows(rows)
    os.replace(tmp, path)


def summary_path(out: Path) -> Path:
    return out.with_name(out.stem + " - summary.csv")


def write_results(src: Path, out: Path, records: dict[int, dict[str, Any]], meta: dict[str, Any]) -> None:
    """Questions CSV + result columns -> `out`; the run summary goes next to it as '<out> - summary.csv'."""
    header, rows = load_table(src)
    id_header = id_column(header, rows)
    header += [name for _, name in RESULT_COLUMNS if name not in header]  # an input with results reuses them
    for row in rows:
        record = records.get(_as_int(row.get(id_header)) or -1)
        if record:
            row.update({name: clean(record.get(key)) for key, name in RESULT_COLUMNS})
    out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(out, header, rows)

    done = list(records.values())
    summary: list[list[Any]] = [["Run summary", None], *([k, v] for k, v in meta.items()), [None, None]]
    summary.append(["Auto verdict", "Questions"])
    for verdict in ("PASS", "PARTIAL", "FAIL", "UNJUDGED", ""):
        count = sum(1 for r in done if (r.get("verdict") or "") == verdict)
        if count:
            summary.append([verdict or "(not judged)", count])
    summary += [[None, None], ["Category", "PASS", "PARTIAL", "FAIL", "Other", "Total"]]
    for cat in sorted({r.get("category") or "" for r in done}):
        mine = [r for r in done if (r.get("category") or "") == cat]
        counts = [sum(1 for r in mine if r.get("verdict") == v) for v in ("PASS", "PARTIAL", "FAIL")]
        summary.append([cat, *counts, len(mine) - sum(counts), len(mine)])
    write_csv(summary_path(out), [], summary)


# --- the run -------------------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> int:
    from infopave_mcp import kb  # noqa: PLC0415

    if pack_is_sample() and not args.allow_sample:
        sys.exit(
            f"INFOPAVE_DATA_DIR points at the small sample pack ({os.environ['INFOPAVE_DATA_DIR']}). "
            "Set it to the full data pack (e.g. D:\\Office Work\\MCP Server\\data_pack), or pass --allow-sample."
        )
    source = Path(args.questions)
    questions = read_questions(source)
    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    if args.verdicts:
        wanted_verdicts = {v.strip().upper() for v in args.verdicts.split(",")}
        questions = [q for q in questions if str(q.get("prev_verdict") or "").upper() in wanted_verdicts]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        sys.exit("No questions selected.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out:
        out = Path(args.out)
    elif args.resume and (earlier := sorted(RESULTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)):
        out = earlier[-1].with_suffix(".csv")  # --resume without --out continues the latest run
    else:
        out = RESULTS_DIR / f"{source.stem} - results {stamp}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = out.with_suffix(".jsonl")
    trace_file = out.with_name(out.stem + " - trace.jsonl")  # every model turn and the full tool results
    records: dict[int, dict[str, Any]] = {}
    if args.resume and checkpoint.is_file():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                records[rec["id"]] = rec
        print(f"resuming: {len(records)} questions already done in {checkpoint.name}")

    model = args.model or os.environ.get("INFOPAVE_EVAL_MODEL") or FALLBACK_MODEL
    judge_model = args.judge_model or model
    llm = make_client()
    preflight(llm, model)
    system = kb.system_prompt()
    meta = {
        "Run started": datetime.now().isoformat(timespec="seconds"),
        "Questions file": source.name,
        "Data pack": os.environ["INFOPAVE_DATA_DIR"],
        "Model (answers)": model,
        "Model (judge)": "not used (--no-judge)" if args.no_judge else judge_model,
        "Max turns per question": args.max_turns,
        "Rerun of verdicts": args.verdicts or "(all)",
        "Trace file": trace_file.name,
        "Questions in this run": len(questions),
    }

    async with open_session() as session:
        for n, q in enumerate(questions, 1):
            if q["id"] in records and not records[q["id"]].get("error"):
                continue
            started = time.time()
            record: dict[str, Any] = {"id": q["id"], "category": q["category"]}
            try:
                result = await ask(llm, session, q["question"], system, model, args.max_turns)
                names, detail = format_calls(result["calls"])
                answer = result["answer"].strip()
                if result.get("hit_turn_limit"):
                    answer = (answer + "\n\n[stopped: turn limit reached]").strip()
                record.update(
                    answer=answer, tool_names=names, tool_calls=detail, n_calls=len(result["calls"]),
                    tool_errors=result["errors"], turns=result["turns"],
                    tokens_in=result["tokens_in"], tokens_out=result["tokens_out"],
                    **diagnostics(q, {**result, "answer": answer}),
                )  # fmt: skip
                trace = {"id": q["id"], "question": q["question"], "model": model,
                         "system_prompt_chars": len(system), "turns": result["trace"]}  # fmt: skip
                with trace_file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(trace, ensure_ascii=False, default=str) + "\n")
            except Exception as exc:  # noqa: BLE001 - keep going; the row records what happened
                record.update(answer="", error=f"{type(exc).__name__}: {exc}")
            record["seconds"] = round(time.time() - started, 1)
            if args.no_judge:
                record["verdict"], record["verdict_reason"] = None, None
            elif record.get("error"):
                record["verdict"], record["verdict_reason"] = "FAIL", "the run failed before an answer was produced"
            else:
                record["verdict"], record["verdict_reason"] = judge(llm, judge_model, q, record["answer"])
            records[q["id"]] = record
            with checkpoint.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            write_results(source, out, records, meta)
            print(
                f"[{n}/{len(questions)}] id {q['id']}: {record.get('verdict') or '-'}  "
                f"{record.get('n_calls', 0)} tool calls, {record['seconds']}s"
                + (f"  ERROR {record['error']}" if record.get("error") else "")
            )

    write_results(source, out, records, meta | {"Run finished": datetime.now().isoformat(timespec="seconds")})
    verdicts = [r.get("verdict") for r in records.values()]
    print(f"\nWrote {out}\n      {summary_path(out)}")
    if not args.no_judge:
        print(
            "  "
            + ", ".join(f"{v}: {verdicts.count(v)}" for v in ("PASS", "PARTIAL", "FAIL", "UNJUDGED") if v in verdicts)
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--questions", "--workbook", dest="questions", default=str(DEFAULT_QUESTIONS), help="the questions CSV"
    )
    parser.add_argument("--out", help="output .csv (default: eval/local/results/<name> - results <time>.csv)")
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument(
        "--verdicts",
        help="rerun only questions whose Auto verdict in --questions is one of these, e.g. FAIL or FAIL,PARTIAL "
        "(--questions must then be a results file)",
    )
    parser.add_argument("--limit", type=int, help="run only the first N selected questions")
    parser.add_argument("--model", help="Bedrock model id for answering (or INFOPAVE_EVAL_MODEL)")
    parser.add_argument("--judge-model", help="Bedrock model id for the verdicts (default: same as --model)")
    parser.add_argument("--max-turns", type=int, default=25, help="model/tool round trips allowed per question")
    parser.add_argument("--no-judge", action="store_true", help="skip the automatic verdict column")
    parser.add_argument("--resume", action="store_true", help="continue from the .jsonl checkpoint next to --out")
    parser.add_argument("--allow-sample", action="store_true", help="allow running against the small sample pack")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
