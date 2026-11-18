"""Read rows of one section from one table, with units and code meanings attached."""

from datetime import date
from typing import Any

from infopave_mcp.models import Cond, DateRange, Page, Select
from infopave_mcp.repository.base import Repository, Row
from infopave_mcp.services import fields
from infopave_mcp.services.sections import SectionRef

KEY_COLUMNS = ("state_code", "shrp_id")


def section_conds(ref: SectionRef) -> list[Cond]:
    return [Cond("STATE_CODE", "eq", ref.state_code), Cond("SHRP_ID", "eq", ref.shrp_id)]


def date_conds(column: str, rng: DateRange | None) -> list[Cond]:
    conds: list[Cond] = []
    if rng is None:
        return conds
    if rng.start_date:
        conds.append(Cond(column, "ge", date.fromisoformat(rng.start_date)))
    if rng.end_date:
        # include the whole end day
        conds.append(Cond(column, "le", date.fromisoformat(rng.end_date)))
    return conds


def read_section_rows(
    repo: Repository,
    table: str,
    ref: SectionRef,
    *,
    construction_no: int | None = None,
    extra: list[Cond] | None = None,
    date_column: str | None = None,
    dates: DateRange | None = None,
    order_by: list[tuple[str, bool]] | None = None,
    page: Page | None = None,
    columns: list[str] | None = None,
    units: str = "stored",
    drop: tuple[str, ...] = KEY_COLUMNS,
    skip_codes: tuple[str, ...] = (),
) -> tuple[list[Row], dict[str, dict[str, Any]], int]:
    """Rows for one section: (rows, fields metadata, total matching before paging)."""
    where = section_conds(ref)
    if construction_no is not None and repo.has_column(table, "CONSTRUCTION_NO"):
        where.append(Cond("CONSTRUCTION_NO", "eq", construction_no))
    where += extra or []
    if date_column:
        where += date_conds(date_column, dates)
    sel = Select(
        table=table,
        columns=columns,
        where=where,
        order_by=order_by or [],
        limit=page.limit if page else None,
        offset=page.offset if page else 0,
    )
    rows, total = repo.select(sel)
    shaped, meta = fields.shape(repo, table, rows, units, drop=drop, skip_codes=skip_codes)
    return shaped, meta, total
