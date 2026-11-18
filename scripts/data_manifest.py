"""Build or verify manifest.json for the LTPP data pack.

  python scripts/data_manifest.py build  ./data --release "LTPP SDR 40"
  python scripts/data_manifest.py verify ./data

build  : records every .parquet file's size, SHA-256, row count and column count
         (row/column counts need duckdb, which the server already installs).
verify : checks every file listed is present, unchanged and that no extra
         .parquet files exist. Uses only the standard library, so CI needs no installs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(folder: Path, release: str) -> None:
    import duckdb  # only needed for build

    con = duckdb.connect()
    files = {}
    for p in sorted(folder.glob("*.parquet")):
        q = str(p).replace("'", "''")
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{q}')").fetchone()[0]
        cols = len(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{q}')").fetchall())
        files[p.name] = {"bytes": p.stat().st_size, "sha256": sha256(p), "rows": rows, "columns": cols}
        print(f"  {p.name}: {rows:,} rows, {cols} columns")

    manifest = {
        "data_release": release,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_rows": sum(f["rows"] for f in files.values()),
        "files": files,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {folder / MANIFEST}: {len(files)} files, {manifest['total_rows']:,} rows")


def verify(folder: Path) -> int:
    path = folder / MANIFEST
    if not path.exists():
        print(f"FAIL: {path} not found")
        return 1
    manifest = json.loads(path.read_text())
    expected = manifest["files"]
    actual = {p.name for p in folder.glob("*.parquet")}
    problems = []
    for name, meta in expected.items():
        p = folder / name
        if name not in actual:
            problems.append(f"missing: {name}")
        elif p.stat().st_size != meta["bytes"] or sha256(p) != meta["sha256"]:
            problems.append(f"changed: {name}")
    for name in sorted(actual - set(expected)):
        problems.append(f"not in manifest: {name}")

    if problems:
        print("FAIL:\n  " + "\n  ".join(problems))
        return 1
    print(f"OK: {len(expected)} files match the manifest ({manifest.get('data_release', '')})")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "verify"])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--release", default="LTPP Standard Data Release 40")
    args = ap.parse_args()
    if args.command == "build":
        build(args.folder, args.release)
    else:
        sys.exit(verify(args.folder))


if __name__ == "__main__":
    main()
