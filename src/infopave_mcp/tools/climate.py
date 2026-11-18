"""Climate (ARCLD): section climate by year and month, binder temperatures, and group comparisons."""

from typing import Any, Literal

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Cond, Envelope, Page, SectionGroup, Select, make_group
from infopave_mcp.models.inputs import ClimateGroup, ClimateVariable, Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.climate import BINDER, GROUPS, KEYS, VARS, cell_summary, columns_for, grid_cell
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.services.units import conversion_for, convert_number

Detail = Literal["summary", "full"]


def _year_conds(
    start_year: int | None, end_year: int | None, month: int | None = None, year_col: str = "YEAR"
) -> list[Cond]:
    conds: list[Cond] = []
    if start_year is not None:
        conds.append(Cond(year_col, "ge", start_year))
    if end_year is not None:
        conds.append(Cond(year_col, "le", end_year))
    if month is not None:
        conds.append(Cond("MONTH", "eq", month))
    return conds


def _climate(
    state: str,
    shrp_id: str,
    variables: list[str] | None,
    start_year: int | None,
    end_year: int | None,
    detail: str,
    units: str,
    limit: int,
    offset: int,
    monthly: bool,
    month: int | None = None,
) -> Envelope:
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    cell = grid_cell(repo, ref)
    page = Page.of(limit, offset)
    chosen: list[str] = list(dict.fromkeys(variables if variables else list(GROUPS)))
    unknown = [v for v in chosen if v not in GROUPS]
    if unknown:
        raise ValueError(f"Unknown variable group(s) {unknown}. Choose from: {', '.join(GROUPS)}.")

    merged: dict[tuple[int, int], dict[str, Any]] = {}
    metas: list[dict[str, dict[str, Any]]] = []
    sources = ["LDW_DP_GENERAL", "MERRA_GRID_SECTION"]
    period_means: dict[str, dict[str, float]] = {}
    for group in chosen:
        annual_table, monthly_table, _ = GROUPS[group]
        table = monthly_table if monthly else annual_table
        cols = columns_for(repo, table, group, detail)
        rows, _ = repo.select(
            Select(
                table,
                columns=cols,
                where=[Cond("MERRA_ID", "eq", cell["merra_id"]), *_year_conds(start_year, end_year, month)],
            )
        )
        shaped, meta = fields.shape(repo, table, rows, units, drop=("merra_id",))
        sources.append(table)
        metas.append({f"{group}.{k}": v for k, v in meta.items() if k not in KEYS})
        for r in shaped:
            key = (int(r["year"]), int(r.get("month", 0)))
            slot = merged.setdefault(key, {"year": key[0], **({"month": key[1]} if monthly else {})})
            slot[group] = {k: v for k, v in r.items() if k not in KEYS and v is not None}
        if not monthly:
            means: dict[str, float] = {}
            for col in {k for r in shaped for k in r if k not in KEYS}:
                vals = [r[col] for r in shaped if isinstance(r.get(col), (int, float))]
                if vals:
                    means[col] = round(sum(vals) / len(vals), 3)
            if means:
                period_means[group] = means

    ordered = [merged[k] for k in sorted(merged, reverse=True)]
    total = len(ordered)
    shown = ordered[page.offset : page.offset + page.limit]
    data: dict[str, Any] = {
        "section": ref.key(),
        "grid_cell": cell_summary(cell),
        "resolution": "monthly" if monthly else "annual",
        "rows": shown,
        "fields": {k: v for m in metas for k, v in m.items()},
    }
    if not monthly:
        data["period_means"] = period_means
        data["years_in_period"] = total
    notes = [cv.SECTION_KEY, cv.CLIMATE_SCOPE, cv.CLIMATE_MODELLED, cv.CELLS_SHARED, cv.units_note(units)]
    if not shown:
        notes.append("No climate rows fall in this period.")
    return respond(
        data, sources=sources, caveats=notes, decoded=True, page=page, total_count=total, returned=len(shown)
    )


def get_section_climate_annual(
    state: str,
    shrp_id: str,
    variables: list[ClimateGroup] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    detail: Detail = "summary",
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Yearly climate for the grid cell serving a section, 1980 to 2025 (MERRA-2).

    variables: any of temperature (air temperature, freezing index, freeze-thaw days, days above 32 C and
        below 0 C), precipitation (precipitation, evaporation, wet days), humidity, wind, solar (radiation,
        cloud cover, sunshine, albedo). Default: all five. detail="summary" shows the main columns; "full"
        every column (soil temperatures, standard deviations...). `period_means` averages each column over
        the years selected. start_year / end_year: window. Newest year first.
    Temperatures are deg C, precipitation mm (units="us" gives deg F and inches).
    limit / offset: page through years (page size capped at 50; use next_offset).
    """
    return _climate(
        state,
        shrp_id,
        list(variables) if variables else None,
        start_year,
        end_year,
        detail,
        units,
        limit,
        offset,
        monthly=False,
    )


def get_section_climate_monthly(
    state: str,
    shrp_id: str,
    variables: list[ClimateGroup] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    month: int | None = None,
    detail: Detail = "summary",
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Monthly climate for the grid cell serving a section, 1980 to 2025 (MERRA-2): the same variables as
    get_section_climate_annual (temperature, precipitation, humidity, wind, solar) for each month.

    month: keep one calendar month (1-12), e.g. 1 for every January. start_year / end_year: window.
    Newest month first. Daily and hourly data are not in the pack.
    limit / offset: page through months (page size capped at 50; use next_offset).
    """
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12.")
    return _climate(
        state,
        shrp_id,
        list(variables) if variables else None,
        start_year,
        end_year,
        detail,
        units,
        limit,
        offset,
        monthly=True,
        month=month,
    )


def get_binder_temperature_summary(
    state: str,
    shrp_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Yearly temperature extremes relevant to asphalt binder grading for a section's grid cell:
    coldest air temperature, hottest 7-day average and maximum, minimum pavement surface temperatures at
    50% and 98% reliability, and mean temperature over 10 C. Newest year first. A `period_summary` gives the
    coldest and hottest values across the years selected. The data dictionary documents no units for this
    table, so values are as stored and cannot be converted.
    limit / offset: page through years (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    cell = grid_cell(repo, ref)
    page = Page.of(limit, offset)
    rows, _ = repo.select(
        Select(
            BINDER,
            where=[
                Cond("MERRA_ID", "eq", cell["merra_id"]),
                *_year_conds(start_year, end_year, year_col="MERRA_YEAR"),
            ],
            order_by=[("MERRA_YEAR", True)],
        )
    )
    shaped, meta = fields.shape(repo, BINDER, rows, units, drop=("merra_id",))
    summary: dict[str, Any] = {}
    for col in ("coldest_air_temp", "high_temp_7days", "max_temp_high_7days", "min_surface_98_temp"):
        vals = [r[col] for r in shaped if isinstance(r.get(col), (int, float))]
        if vals:
            summary[col] = {"min": min(vals), "max": max(vals)}
    total = len(shaped)
    shown = [fields.compact(r) for r in shaped[page.offset : page.offset + page.limit]]
    return respond(
        {
            "section": ref.key(),
            "grid_cell": cell_summary(cell),
            "period_summary": summary,
            "years": shown,
            "fields": meta,
        },  # fmt: skip
        sources=["LDW_DP_GENERAL", "MERRA_GRID_SECTION", BINDER],
        caveats=[
            cv.SECTION_KEY,
            cv.CLIMATE_SCOPE,
            cv.CLIMATE_MODELLED,
            "The data dictionary gives no units for the binder-temperature columns; values are as stored.",
        ],  # fmt: skip
        decoded=True,
        page=page,
        total_count=total,
        returned=len(shown),
    )


def compare_climate_between_groups(
    group_a: SectionGroup,
    group_b: SectionGroup,
    variables: list[ClimateVariable] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    months: list[int] | None = None,
    units: Units = "stored",
) -> Envelope:
    """Compare two groups of test sections on climate variables (MERRA-2, yearly or by chosen months).

    group_a / group_b: each an object with optional fields: label, state (or states), region, climate_zone
        (wet-freeze, wet-no-freeze, dry-freeze, dry-no-freeze), experiment, gps_sps, top_layer (AC or PCC),
        functional_class, monitoring_status, county, constructed_after, constructed_before, near_latitude
        + near_longitude + radius_km, and min_ac_thickness_in / max_ac_thickness_in (asphalt thickness of the
        section's latest structure with asphalt layers). Example: {"label": "Northern", "states": ["MN", "WI"]}.
    variables: air_temperature_avg/max/min, freeze_index, freeze_thaw_days, days_above_32c, days_below_0c,
        precipitation, evaporation, precipitation_days, relative_humidity_avg, time_of_wetness,
        wind_speed_avg, solar_radiation, cloud_cover, percent_sunshine. Default: temperature, freeze index,
        freeze-thaw days and precipitation.
    start_year / end_year: years averaged (default all, 1980-2025). months: use only these calendar months
        (switches to the monthly tables, e.g. [12, 1, 2] for winter).
    For each variable: every section's mean over the period, then the distribution across each group's
    sections (count, mean, median, SD, quartiles, min, max), the difference of means (A - B) and an effect
    size (Cohen's d). units: stored, us or si.
    """
    repo = get_repository()
    a = make_group(group_a, "Group A")
    b = make_group(group_b, "Group B")
    for g in (a, b):
        if g.pavement_class:
            raise ValueError("pavement_class applies to performance measures, not climate; remove it from the group.")
        if g.is_empty() and g.min_ac_thickness_in is None and g.max_ac_thickness_in is None:
            raise ValueError("Each group needs at least one filter (e.g. a state, climate_zone or region).")
    chosen = list(
        dict.fromkeys(variables or ["air_temperature_avg", "freeze_index", "freeze_thaw_days", "precipitation"])
    )
    bad = [v for v in chosen if v not in VARS]
    if bad:
        raise ValueError(f"Unknown variable(s) {bad}. Choose from: {', '.join(VARS)}.")
    if months and any(not 1 <= m <= 12 for m in months):
        raise ValueError("months must be between 1 and 12.")

    out: list[dict[str, Any]] = []
    sources = ["LDW_DP_GENERAL", "MERRA_GRID_SECTION"]
    for key in chosen:
        var = VARS[key]
        annual, monthly, _ = GROUPS[var.group]
        table = monthly if months else annual
        sources.append(table)
        info = repo.field_info(table).get(var.column.lower())
        stored_unit = info.units if info else None
        conv = conversion_for(stored_unit, units)
        stats = {}
        for label, grp in ((a.title("Group A"), a), (b.title("Group B"), b)):
            s = repo.climate_group_stats(table, var.column, grp, start_year, end_year, months)
            scale = (conv.convert(1.0) - conv.convert(0.0)) if conv else 1.0
            if conv:
                for k in ("mean", "median", "min", "max", "p25", "p75"):
                    s[k] = convert_number(s[k], conv)
                s["std_dev"] = round(s["std_dev"] * scale, 4) if s.get("std_dev") is not None else None
            stats[label] = s
        (la, sa), (lb, sb) = list(stats.items())
        entry: dict[str, Any] = {
            "variable": key, "title": var.title, "units": conv.to_unit if conv else stored_unit,
            "groups": stats,
        }  # fmt: skip
        if sa["mean"] is not None and sb["mean"] is not None:
            entry["difference_a_minus_b"] = round(sa["mean"] - sb["mean"], 4)
            na, nb = sa["sections"], sb["sections"]
            if na > 1 and nb > 1 and sa["std_dev"] is not None and sb["std_dev"] is not None:
                pooled = (((na - 1) * sa["std_dev"] ** 2 + (nb - 1) * sb["std_dev"] ** 2) / (na + nb - 2)) ** 0.5
                if pooled > 0:
                    entry["cohens_d"] = round((sa["mean"] - sb["mean"]) / pooled, 3)
        out.append(entry)
    empty = [e["variable"] for e in out if any(g["sections"] == 0 for g in e["groups"].values())]
    notes = [cv.CLIMATE_SCOPE, cv.CLIMATE_MODELLED, cv.CELLS_SHARED, cv.units_note(units)]
    if any(g.min_ac_thickness_in is not None or g.max_ac_thickness_in is not None for g in (a, b)):
        notes.append(cv.CONSTRUCTION_BASIS)
    if empty:
        notes.append("A group matched no sections for: " + ", ".join(empty) + ".")
    return respond(
        {
            "period": {"start_year": start_year, "end_year": end_year, "months": months},
            "comparison": out,
        },
        sources=sources,
        caveats=notes,
        decoded=True,
    )


def register(mcp: FastMCP) -> None:
    for tool in (
        get_section_climate_annual,
        get_section_climate_monthly,
        get_binder_temperature_summary,
        compare_climate_between_groups,
    ):
        mcp.tool()(tool)
