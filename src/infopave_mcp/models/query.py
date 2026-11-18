"""A small, backend-neutral description of table queries.

Tools and services build these; each repository backend turns them into its own SQL. Column names are
validated against the data pack's schema by the backend, so nothing a caller types reaches SQL as text.
"""

from dataclasses import dataclass, field
from typing import Any

# eq ne gt ge lt le  in  like (case-insensitive "contains")  isnull notnull
OPS = {"eq", "ne", "gt", "ge", "lt", "le", "in", "like", "isnull", "notnull"}


@dataclass(frozen=True)
class Cond:
    column: str
    op: str = "eq"
    value: Any = None

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"Unknown condition operator '{self.op}'.")


@dataclass
class Aggregate:
    """Group one table's rows and summarise them.

    Result columns: each group_by column; `n_rows` (how many source rows); each `avg` column (mean); for each
    `minmax` column `<col>_min` and `<col>_max`; each `flags` column as the sorted list of its distinct
    non-null values.
    """

    table: str
    group_by: list[str]
    avg: list[str] = field(default_factory=list)
    minmax: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    where: list[Cond] = field(default_factory=list)
    order_by: list[tuple[str, bool]] = field(default_factory=list)  # group_by columns only
    limit: int | None = None
    offset: int = 0
    digits: int = 3


@dataclass(frozen=True)
class MeasureSpec:
    """A single performance measure: where it lives and how it pairs with treatment records."""

    key: str
    title: str
    table: str
    value: str  # the column that is summarised
    date: str  # the measurement date column
    flags: tuple[str, ...] = ()  # columns whose non-null value marks a possible anomaly
    interval: str = "profile"  # which prior/post interval of ANALYSIS_MNT_RHB_SUMMARY applies


@dataclass
class Select:
    table: str
    columns: list[str] | None = None  # None = every column
    where: list[Cond] = field(default_factory=list)
    order_by: list[tuple[str, bool]] = field(default_factory=list)  # (column, descending)
    limit: int | None = None
    offset: int = 0
    distinct: bool = False
