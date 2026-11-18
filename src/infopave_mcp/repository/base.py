"""The data-access contract. Tools and services only talk to this interface, never to SQL.

Backends override the methods they support; anything left alone raises NotImplementedError, so an
unfinished backend fails loudly instead of returning wrong answers. Rows are plain dicts whose keys are
the LTPP column names in lower case.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from infopave_mcp.models.inputs import DateRange, Page, SectionFilter, SectionGroup
from infopave_mcp.models.query import Aggregate, Cond, MeasureSpec, Select

Row = dict[str, Any]


@dataclass(frozen=True)
class FieldInfo:
    """What the data dictionary (LDW_PPDB_DD) says about one column."""

    name: str  # lower case
    data_type: str | None = None
    units: str | None = None
    code_type: str | None = None
    description: str | None = None


class Repository:
    name = "base"

    def _todo(self, method: str) -> Any:
        raise NotImplementedError(f"The '{self.name}' backend does not implement {method}() yet.")

    # --- Data pack metadata -------------------------------------------------------------------
    def data_release(self) -> Row:
        """Latest LTPP Standard Data Release: {"id", "name", "label"} (label e.g. "SDR 40 (September, 2026)")."""
        return self._todo("data_release")

    def list_tables(self) -> list[str]:
        return self._todo("list_tables")

    def omitted_columns(self) -> dict[str, list[str]]:
        """Columns that exist in the data pack but are not served, by table (empty if none)."""
        return {}

    def has_column(self, table: str, column: str) -> bool:
        return self._todo("has_column")

    def table_columns(self, table: str) -> list[Row]:
        """[{"column_name", "column_type"}] for one table."""
        return self._todo("table_columns")

    def manifest(self) -> Row:
        return self._todo("manifest")

    def table_catalog(self) -> list[Row]:
        """Title and description of every table in the pack, from the LTPP table dictionary."""
        return self._todo("table_catalog")

    def field_info(self, table: str) -> dict[str, FieldInfo]:
        """Dictionary entries for the columns of one table, keyed by lower-case column name."""
        return self._todo("field_info")

    def code_labels(self, code_type: str) -> dict[str, str]:
        """code -> meaning for one code type (CODES table)."""
        return self._todo("code_labels")

    def code_types(self) -> list[Row]:
        return self._todo("code_types")

    # --- Generic access ------------------------------------------------------------------------
    def select(self, sel: Select) -> tuple[list[Row], int]:
        """Rows from one table, and how many rows matched before limit/offset."""
        return self._todo("select")

    def aggregate(self, agg: Aggregate) -> tuple[list[Row], int]:
        """Grouped summary of one table: (rows, number of groups before limit/offset)."""
        return self._todo("aggregate")

    def count(self, table: str, where: list[Cond]) -> int:
        return self._todo("count")

    def section_tables(self) -> list[str]:
        """Data tables keyed by section (STATE_CODE and SHRP_ID), other than the section table itself."""
        return self._todo("section_tables")

    def dataset_counts(self, state_code: int, shrp_id: str, tables: list[str]) -> dict[str, int]:
        """Rows each table holds for one section (tables must have STATE_CODE and SHRP_ID)."""
        return self._todo("dataset_counts")

    # --- Sections ------------------------------------------------------------------------------
    def find_section(self, state_code: int, shrp_id: str) -> Row | None:
        return self._todo("find_section")

    def similar_section_ids(self, state_code: int, shrp_id: str) -> list[str]:
        return self._todo("similar_section_ids")

    def search_sections(self, f: SectionFilter, page: Page) -> tuple[list[Row], int]:
        return self._todo("search_sections")

    def group_sections(self, group_by: str, f: SectionFilter, page: Page) -> tuple[list[Row], int, Row]:
        """(groups, number of groups, totals)."""
        return self._todo("group_sections")

    # --- Materials -----------------------------------------------------------------------------
    def numeric_columns(self, table: str) -> list[str]:
        return self._todo("numeric_columns")

    def material_group_stats(
        self,
        table: str,
        column: str,
        group_by: str,
        f: SectionFilter,
        layer_types: list[str] | None,
        page: Page,
    ) -> tuple[list[Row], int, Row]:
        """Statistics of one numeric layer property grouped by a section attribute or the layer type.

        Returns (groups, number of groups, overall statistics for all matching layers).
        """
        return self._todo("material_group_stats")

    # --- Performance ---------------------------------------------------------------------------
    def performance_groups(
        self,
        measure: MeasureSpec,
        group_by: str,
        f: SectionFilter,
        families: list[str] | None,
        age_bin_years: int,
        max_age_years: float | None,
        exclude_flagged: bool,
        page: Page,
    ) -> tuple[list[Row], int, Row]:
        """Progression of a measure by group and pavement-age bin: (rows, total rows, overall statistics)."""
        return self._todo("performance_groups")

    # --- Climate -------------------------------------------------------------------------------
    def climate_group_stats(
        self,
        table: str,
        column: str,
        group: SectionGroup,
        start_year: int | None,
        end_year: int | None,
        months: list[int] | None,
    ) -> Row:
        """Distribution, across the sections of a group, of each section's mean of one climate column."""
        return self._todo("climate_group_stats")

    # --- Treatments ----------------------------------------------------------------------------
    def treatment_pairs(
        self,
        measure: MeasureSpec,
        *,
        state_code: int,
        shrp_id: str,
        maint_codes: list[str] | None,
        surface_codes: list[str],
        exclude_flagged: bool,
        dates: DateRange | None,
    ) -> list[Row]:
        """For each treatment of one section: the measurement before and after, and whether the pair is valid."""
        return self._todo("treatment_pairs")

    def treatment_effect(
        self,
        measure: MeasureSpec,
        group: SectionGroup,
        *,
        maint_codes: list[str] | None,
        surface_codes: list[str],
        exclude_flagged: bool,
        group_by: str | None,
        page: Page,
    ) -> tuple[list[Row], int, dict[str, int]]:
        """Before/after change statistics for valid treatment pairs: (rows per group, groups, status counts)."""
        return self._todo("treatment_effect")

    def find_sections(self, criteria: dict[str, Any], f: SectionFilter, page: Page) -> tuple[list[Row], int]:
        """Sections matching climate, material, traffic, treatment and performance criteria together."""
        return self._todo("find_sections")

    # --- Table sizes ----------------------------------------------------------------
    def table_sizes(self) -> list[Row]:
        """[{"table", "rows"}] for every table in the pack."""
        return self._todo("table_sizes")

    # --- Convenience for services --------------------------------------------------------------
    @staticmethod
    def window(rng: DateRange) -> tuple[date | None, date | None]:
        s, e = rng.start_date, rng.end_date
        return (date.fromisoformat(s) if s else None, date.fromisoformat(e) if e else None)
