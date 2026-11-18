"""Attach units and code meanings to rows, using the LTPP data dictionary and CODES table.

Rows keep their raw values. Alongside them a `fields` block says, for each column that needs it, what its
units are and what each code present in the rows means. With units="us" or "si", columns stored in the
other system are converted and the block records the original unit.
"""

from typing import Any

from infopave_mcp.repository.base import FieldInfo, Repository, Row
from infopave_mcp.services.units import conversion_for, convert_number

SKIP_CODE_TYPES = {"COUNTY"}  # repeats per state; the section table already carries the county name


def _code_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def shape(
    repo: Repository,
    table: str,
    rows: list[Row],
    units: str = "stored",
    *,
    drop: tuple[str, ...] = (),
    skip_codes: tuple[str, ...] = (),
) -> tuple[list[Row], dict[str, dict[str, Any]]]:
    """Return (rows without `drop` columns, fields metadata). Converts units in place when asked."""
    info = repo.field_info(table)
    out = [{k: v for k, v in r.items() if k not in drop} for r in rows]
    columns: list[str] = []
    for r in out:
        for k in r:
            if k not in columns:
                columns.append(k)

    fields: dict[str, dict[str, Any]] = {}
    for col in columns:
        meta: dict[str, Any] = {}
        fi = info.get(col)
        if fi is None and col.endswith(("_min", "_max")):
            fi = info.get(col[:-4])  # a minimum or maximum of a documented column keeps its units
            if fi is not None:
                fi = FieldInfo(name=col, units=fi.units)
        if fi is None:
            continue
        if fi.units:
            conv = conversion_for(fi.units, units)
            if conv is not None:
                for r in out:
                    if col in r:
                        r[col] = convert_number(r[col], conv)
                meta["units"] = conv.to_unit
                meta["converted_from"] = fi.units
            else:
                meta["units"] = fi.units
        if fi.code_type and fi.code_type.upper() not in SKIP_CODE_TYPES and col not in skip_codes:
            labels = repo.code_labels(fi.code_type)
            present = {key for r in out if (key := _code_key(r.get(col))) is not None}
            legend = {k: labels[k] for k in sorted(present) if k in labels}
            if legend:
                meta["codes"] = legend
        if meta:
            fields[col] = meta
    return out, fields


def merge_fields(*blocks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Combine fields blocks from several tables; the first block to describe a column wins."""
    merged: dict[str, dict[str, Any]] = {}
    for block in blocks:
        for col, meta in block.items():
            if col not in merged:
                merged[col] = meta
            elif "codes" in meta and "codes" in merged[col]:
                merged[col]["codes"] = {**merged[col]["codes"], **meta["codes"]}
    return merged


def compact(row: Row, *, keep: tuple[str, ...] = ()) -> Row:
    """Drop null values (keeping any named columns), for wide records where most columns are empty."""
    return {k: v for k, v in row.items() if v is not None or k in keep}
