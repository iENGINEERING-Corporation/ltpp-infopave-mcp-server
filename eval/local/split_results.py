"""Split a results CSV by verdict, or merge a rerun back into it.

python -m eval.local.split_results "eval/local/results/<name>.csv"
    writes "<name> - PASS.csv", "<name> - PARTIAL.csv" and "<name> - FAIL.csv" next to it. Each has the
    same columns; only the questions with that verdict are kept.

python -m eval.local.run_workbook_eval --questions "eval/local/results/<name> - FAIL.csv" --verdicts FAIL
    reruns just those questions (the FAIL file is a valid input: it has the same columns).

python -m eval.local.split_results "eval/local/results/<name>.csv" --merge "eval/local/results/<rerun>.csv"
    copies the rerun's results over the matching question ids and writes "<name> - merged.csv", so the
    full picture is always one file.
"""

import argparse
import sys
from pathlib import Path

from eval.local.run_workbook_eval import RESULT_COLUMNS, _as_int, id_column, load_table, write_csv

VERDICT_HEADER = "Auto verdict"
VERDICTS = ("PASS", "PARTIAL", "FAIL")
RESULT_HEADERS = {name for _, name in RESULT_COLUMNS}


def split(path: Path, out_dir: Path) -> list[Path]:
    header, rows = load_table(path)
    written = []
    for verdict in VERDICTS:
        kept = [r for r in rows if r.get(VERDICT_HEADER, "").upper() == verdict]
        target = out_dir / f"{path.stem} - {verdict}.csv"
        write_csv(target, header, kept)
        written.append(target)
        print(f"{verdict:8} {len(kept):3} questions -> {target}")
    return written


def merge(base: Path, rerun: Path, out: Path) -> None:
    header, rows = load_table(base)
    new_header, new_rows = load_table(rerun)
    id_header = id_column(header, rows)
    by_id = {_as_int(r.get(id_column(new_header, new_rows))): r for r in new_rows}
    # result columns the base does not have yet (e.g. new diagnostics) are appended
    header += [h for h in new_header if h in RESULT_HEADERS and h not in header]
    for row in rows:
        src = by_id.get(_as_int(row.get(id_header)))
        if src is not None:
            row.update({h: src.get(h, "") for h in new_header if h in RESULT_HEADERS})
    write_csv(out, header, rows)
    print(f"merged {rerun.name} into {base.name} -> {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", help="a results CSV written by run_workbook_eval")
    parser.add_argument("--merge", help="a rerun's results CSV to copy into the first one")
    parser.add_argument("--out-dir", help="where to write the split files (default: next to the results)")
    args = parser.parse_args(argv)
    path = Path(args.results)
    if not path.is_file():
        sys.exit(f"No such file: {path}")
    if args.merge:
        merge(path, Path(args.merge), path.with_name(f"{path.stem} - merged.csv"))
    else:
        split(path, Path(args.out_dir) if args.out_dir else path.parent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
