"""Helpers shared by the performance tools: flag handling and a simple trend summary."""

from datetime import date, datetime
from typing import Any

from infopave_mcp.repository.base import Repository, Row


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def merge_flags(
    repo: Repository, table: str, rows: list[Row], flag_cols: list[str], out: str = "flags"
) -> dict[str, dict[str, Any]]:
    """Collapse several flag columns of each row into one `flags` list; return its legend for `fields`."""
    info = repo.field_info(table)
    seen: set[str] = set()
    for r in rows:
        merged: set[str] = set()
        for c in flag_cols:
            v = r.pop(c, None)
            if isinstance(v, list):
                merged.update(str(x) for x in v)
            elif v is not None:
                merged.add(str(v))
        if merged:
            r[out] = sorted(merged)
            seen |= merged
    code_type = next((info[c].code_type for c in flag_cols if c in info and info[c].code_type), None)
    if not seen or not code_type:
        return {}
    labels = repo.code_labels(code_type)
    legend = {k: labels[k] for k in sorted(seen) if k in labels}
    return {out: {"codes": legend}} if legend else {}


def trend_summary(rows: list[Row], date_key: str, value_key: str) -> dict[str, Any] | None:
    """First, latest, peak and a least-squares change per year for a time series of rows."""
    pts = [(d, r[value_key]) for r in rows if (d := _as_date(r.get(date_key))) and r.get(value_key) is not None]
    if not pts:
        return None
    pts.sort()
    first, last = pts[0], pts[-1]
    peak = max(pts, key=lambda p: p[1])
    summary: dict[str, Any] = {
        "observations": len(pts),
        "first": {"date": first[0], "value": first[1]},
        "latest": {"date": last[0], "value": last[1]},
        "peak": {"date": peak[0], "value": peak[1]},
    }
    years = [(d - first[0]).days / 365.25 for d, _ in pts]
    span = years[-1] - years[0]
    if len(pts) >= 3 and span >= 1:
        mean_x = sum(years) / len(years)
        mean_y = sum(v for _, v in pts) / len(pts)
        denom = sum((x - mean_x) ** 2 for x in years)
        if denom > 0:
            slope = sum((x - mean_x) * (v - mean_y) for x, (_, v) in zip(years, pts, strict=True)) / denom
            summary["change_per_year"] = round(slope, 4)
    summary["years_observed"] = round(span, 1)
    return summary
