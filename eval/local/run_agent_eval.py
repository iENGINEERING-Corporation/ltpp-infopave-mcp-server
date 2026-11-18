"""Run the gold questions against the server.

  python -m eval.local.run_agent_eval --smoke        deterministic: call the expected tool directly and check
                                                 the envelope (smoke_checks.json). No API key. CI runs this.
  python -m eval.local.run_agent_eval                agent mode: ask Claude each gold question (gold_questions.json) with the server's
                                                 tools and check which tools it used and what it said.
                                                 Needs `pip install ".[eval]"` and ANTHROPIC_API_KEY.

Data: the committed sample pack by default; set INFOPAVE_DATA_DIR to the full pack and add
--full-pack to also check facts that only hold for the full inventory.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from eval.local.asserts import check
from eval.local.harness import EVALS_DIR, ToolResult, call, open_session, pack_is_sample

DEFAULT_MODEL = os.environ.get("INFOPAVE_EVAL_MODEL", "claude-sonnet-5-5")
MAX_TOOL_TEXT = 30_000  # characters of a tool result sent back to the model


def load_questions(only: list[str] | None = None, filename: str = "gold_questions.json") -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = json.loads((EVALS_DIR / filename).read_text(encoding="utf-8"))
    return [q for q in questions if not only or q["id"] in only]


def load_smoke_checks(only: list[str] | None = None) -> list[dict[str, Any]]:
    """Deterministic per-tool checks against the sample pack (smoke_checks.json); CI runs these."""
    return load_questions(only, "smoke_checks.json")


@dataclass
class Outcome:
    id: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    skipped: str | None = None
    detail: str = ""


# --- smoke mode ---------------------------------------------------------------------------------
async def run_smoke_question(client: Any, q: dict[str, Any], full_pack: bool) -> Outcome:
    steps = q.get("smoke")
    if not steps:
        return Outcome(q["id"], True, skipped="agent-only question (no smoke check)")
    steps = steps if isinstance(steps, list) else [steps]

    problems: list[str] = []
    first: ToolResult | None = None
    for step in steps:
        result = await call(client, step["tool"], step.get("args"))
        first = first or result
        if result.is_error or result.envelope is None:
            problems.append(f"{step['tool']} errored: {result.text[:200]}")
            continue
        env = result.envelope
        for key in ("data", "data_release", "sources", "caveats"):  # the envelope contract
            if key not in env:
                problems.append(f"{step['tool']}: envelope missing '{key}'")
        if not env.get("sources"):
            problems.append(f"{step['tool']}: no sources listed")
        for assertion in step.get("assert", []):
            ok, message = check(env, assertion)
            if not ok:
                problems.append(f"{step['tool']}: {message}")

    skipped = None
    if q.get("full_pack_assert"):
        if full_pack and not pack_is_sample() and first and first.envelope:
            for assertion in q["full_pack_assert"]:
                ok, message = check(first.envelope, assertion)
                if not ok:
                    problems.append(f"full pack: {message}")
        elif full_pack:
            skipped = "full-pack facts skipped (data pack is the sample)"
    return Outcome(q["id"], not problems, problems, skipped=skipped)


async def run_smoke(questions: list[dict[str, Any]], full_pack: bool) -> list[Outcome]:
    async with open_session() as client:
        return [await run_smoke_question(client, q, full_pack) for q in questions]


# --- agent mode ---------------------------------------------------------------------------------
@dataclass
class AgentRun:
    tools_used: list[str] = field(default_factory=list)
    tool_errors: int = 0
    answer: str = ""
    turns: int = 0


async def ask(llm: Any, session: Any, question: str, system: str, model: str, max_turns: int) -> AgentRun:
    """Ask `llm` (an anthropic.Anthropic-like client) a question, letting it call the server's tools."""
    listed = (await session.list_tools()).tools
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in listed]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    run = AgentRun()

    for _ in range(max_turns):
        run.turns += 1
        response = llm.messages.create(model=model, max_tokens=4096, system=system, tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": response.content})
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason != "tool_use":
            run.answer = text
            return run
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            run.tools_used.append(block.name)
            outcome = await session.call_tool(block.name, block.input)
            body = outcome.content[0].text if outcome.content else ""
            run.tool_errors += bool(outcome.is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": body[:MAX_TOOL_TEXT],
                    "is_error": bool(outcome.is_error),
                }
            )
        messages.append({"role": "user", "content": results})
    run.answer = text  # ran out of turns
    return run


def judge(q: dict[str, Any], run: AgentRun) -> Outcome:
    problems = []
    used = set(run.tools_used)
    missing = [t for t in q.get("expected_tools", []) if t not in used]
    if missing:
        problems.append(f"did not call: {', '.join(missing)}")
    for group in q.get("expected_any_of", []):
        if not used.intersection(group):
            problems.append(f"called none of: {', '.join(group)}")
    answer = run.answer.lower()
    for phrase in q.get("answer_must_mention", []):
        if phrase.lower() not in answer:
            problems.append(f"answer does not mention '{phrase}'")
    if not run.answer.strip():
        problems.append("empty answer")
    detail = f"tools: {', '.join(run.tools_used) or '-'} | tool errors: {run.tool_errors} | turns: {run.turns}"
    return Outcome(q["id"], not problems, problems, detail=detail)


async def run_agent(questions: list[dict[str, Any]], model: str, max_turns: int) -> list[Outcome]:
    try:
        import anthropic  # noqa: PLC0415 - optional dependency
    except ImportError:
        sys.exit('Agent mode needs the anthropic package: pip install ".[eval]"  (or use --smoke)')
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Agent mode needs ANTHROPIC_API_KEY (or use --smoke).")

    from infopave_mcp import kb  # noqa: PLC0415

    llm = anthropic.Anthropic()
    outcomes = []
    async with open_session() as session:
        for q in questions:
            run = await ask(llm, session, q["question"], kb.system_prompt(), model, max_turns)
            outcomes.append(judge(q, run))
    return outcomes


# --- reporting ----------------------------------------------------------------------------------
def report(outcomes: list[Outcome]) -> int:
    for o in outcomes:
        status = "SKIP" if o.skipped and o.passed and "agent-only" in o.skipped else ("PASS" if o.passed else "FAIL")
        note = f"  ({o.skipped})" if o.skipped else ""
        print(f"{status}  {o.id}{note}")
        if o.detail:
            print(f"      {o.detail}")
        for p in o.problems:
            print(f"      - {p}")
    failed = [o for o in outcomes if not o.passed]
    ran = [o for o in outcomes if not (o.skipped and "agent-only" in o.skipped)]
    print(
        f"\n{len(ran) - len(failed)}/{len(ran)} passed"
        + (f", {len(outcomes) - len(ran)} skipped" if len(ran) < len(outcomes) else "")
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="deterministic tool checks, no API key")
    parser.add_argument("--full-pack", action="store_true", help="also check facts that hold for the full pack")
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--list", action="store_true", help="list the question ids and exit")
    args = parser.parse_args(argv)

    only = args.only.split(",") if args.only else None
    questions = load_smoke_checks(only) if args.smoke else load_questions(only)
    if args.list:
        for q in questions:
            print(f"{q['id']}: {q['question']}")
        return 0
    if args.smoke:
        outcomes = asyncio.run(run_smoke(questions, args.full_pack))
    else:
        outcomes = asyncio.run(run_agent(questions, args.model, args.max_turns))
    return report(outcomes)


if __name__ == "__main__":
    sys.exit(main())
