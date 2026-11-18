"""Traffic (ARTRD): representative traffic, yearly trend, truck-volume and axle parameters, adjustment factors."""

import re
from typing import Any, Literal

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Cond, Envelope, Page
from infopave_mcp.models.geography import resolve_state, state_name
from infopave_mcp.models.inputs import Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.readers import read_section_rows
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import SectionRef, normalize_shrp_id, resolve_section

DROP = ("state_code", "shrp_id", "record_status", "data_rec_id")
Detail = Literal["summary", "full"]

_CLASS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("vehicle_class_percent", re.compile(r"^rep_percent_veh_class_(\d+)$")),
    ("esal_per_vehicle_class", re.compile(r"^rep_esal_per_veh_class_(\d+)$")),
    ("gesal_per_vehicle_class", re.compile(r"^rep_gesal_per_veh_class_(\d+)$")),
    ("rppif_per_vehicle_class", re.compile(r"^rep_rppif_per_veh_class_(\d+)$")),
    ("gvw_per_vehicle_class", re.compile(r"^rep_gvw_veh_class_(\d+)$")),
]
_AXLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("esal_by_axle_group", re.compile(r"^rep_esal_(single|tandem|tridem|quad)_axle$")),
    ("gesal_by_axle_group", re.compile(r"^rep_gesal_(single|tandem|tridem|quad)_axle$")),
    ("rppif_by_axle_group", re.compile(r"^rep_rppif_(single|tandem|tridem|quad)_axle$")),
]
_PER_TRUCK = {
    "rep_esal_per_truck": "esal_per_truck",
    "rep_gesal_per_truck": "gesal_per_truck",
    "rep_rppif_per_truck": "rppif_per_truck",
    "rep_gvw_truck": "gvw_per_truck",
}
_RATINGS = ("rep_aadtt_use_rating", "rep_veh_class_use_rating", "rep_load_use_rating")


def _structure_rep(row: dict[str, Any], detail: str) -> dict[str, Any]:
    """Turn the 76 flat TRF_REP columns into a readable record."""
    out: dict[str, Any] = {
        "experiment_no": row.get("experiment_no"),
        "gps_sps": row.get("gps_sps"),
        "assign_date": row.get("assign_date"),
        "deassign_date": row.get("deassign_date"),
        "aadtt": row.get("rep_aadtt"),
    }
    blocks: dict[str, dict[str, Any]] = {}
    for col, value in row.items():
        if value is None:
            continue
        for name, pat in _CLASS_PATTERNS + _AXLE_PATTERNS:
            m = pat.match(col)
            if m:
                blocks.setdefault(name, {})[m.group(1)] = value
                break
    out["vehicle_class_percent"] = blocks.pop("vehicle_class_percent", {})
    for col, name in _PER_TRUCK.items():
        if row.get(col) is not None:
            out[name] = row[col]
    if detail == "full":
        out.update(blocks)
    out["use_ratings"] = {c.removeprefix("rep_"): row[c] for c in _RATINGS if row.get(c) is not None}
    return {k: v for k, v in out.items() if v is not None and v != {}}


def get_traffic_summary(state: str, shrp_id: str, detail: Detail = "summary", units: Units = "stored") -> Envelope:
    """Representative traffic for a section: AADTT (annual average daily truck traffic), the percentage of
    trucks in each FHWA vehicle class 4-13, and load measures per truck (ESAL, generic ESAL, RPPIF, gross
    vehicle weight).

    A section may have several records, one per experiment it was assigned to. detail="full" adds the same
    load measures broken down by vehicle class and by axle group (single, tandem, tridem, quad).
    use_ratings say how good the underlying data are (see `fields`). For year-by-year values use
    get_traffic_trend.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    rows, meta, _ = read_section_rows(repo, "TRF_REP", ref, order_by=[("ASSIGN_DATE", False)], units=units, drop=DROP)
    records = [_structure_rep(r, detail) for r in rows]
    notes = [cv.SECTION_KEY, cv.REPRESENTATIVE_TRAFFIC, cv.TRAFFIC_SOURCES, cv.units_note(units)]
    if not records:
        notes.append("No representative traffic record exists for this section.")
    shown_meta = {
        k: v
        for k, v in meta.items()
        if not k.startswith(
            ("rep_percent", "rep_gesal_per_veh", "rep_esal_per_veh", "rep_rppif_per_veh", "rep_gvw_veh")
        )
    }
    return respond(
        {"section": ref.key(), "representative_traffic": records, "fields": shown_meta},
        sources=["TRF_REP", "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


_TREND_SUMMARY = [
    "year", "construction_no", "aadtt_all_trucks_trend", "annual_truck_volume_trend", "annual_esal_trend",
    "annual_gesal_trend", "cmltv_vol_heavy_trucks_trend", "annual_total_gvw_trend",
    "aadtt_source", "esal_source", "gesal_source", "gvw_source",
]  # fmt: skip
_MEASURED = {"M", "MC"}
_ESTIMATED = {"EL", "EC", "S", "H", "D", "A"}


def get_traffic_trend(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    detail: Detail = "summary",
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Yearly traffic for a section: AADTT for all trucks, annual truck volume, annual ESAL and generic ESAL,
    cumulative heavy-truck volume, annual gross vehicle weight, each with a source indicator.

    Each year gets `aadtt_basis`: "measured" (monitored data: M or MC), "estimated" (interpolated, state
    supplied, historical, default or class-based) or "not open" (N), so you can tell data from estimates.
    detail="full" adds AADTT for vehicle classes 4-13 and the class and GVW source columns. A `summary`
    counts measured and estimated years and gives the peak AADTT. start_year / end_year: window. Newest year
    first. limit / offset: page through years (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    extra: list[Cond] = []
    if start_year is not None:
        extra.append(Cond("YEAR", "ge", start_year))
    if end_year is not None:
        extra.append(Cond("YEAR", "le", end_year))
    cols = None
    if detail == "summary":
        cols = [c.upper() for c in _TREND_SUMMARY if repo.has_column("TRF_TREND", c)]
    all_rows, meta, _ = read_section_rows(
        repo, "TRF_TREND", ref, construction_no=construction_no, extra=extra,
        order_by=[("YEAR", True)], columns=cols, units=units, drop=("state_code", "shrp_id"),
    )  # fmt: skip
    for r in all_rows:
        src = r.get("aadtt_source")
        r["aadtt_basis"] = (
            "measured" if src in _MEASURED else "not open" if src == "N" else "estimated" if src in _ESTIMATED else None
        )
    measured = sum(1 for r in all_rows if r.get("aadtt_basis") == "measured")
    estimated = sum(1 for r in all_rows if r.get("aadtt_basis") == "estimated")
    peak = max(
        (r for r in all_rows if r.get("aadtt_all_trucks_trend") is not None),
        key=lambda r: r["aadtt_all_trucks_trend"],
        default=None,
    )
    summary = {
        "years": len(all_rows),
        "measured_years": measured,
        "estimated_years": estimated,
        "peak_aadtt": {"year": peak["year"], "aadtt": peak["aadtt_all_trucks_trend"]} if peak else None,
    }
    shown = [fields.compact(r) for r in all_rows[page.offset : page.offset + page.limit]]
    return respond(
        {"section": ref.key(), "summary": summary, "years": shown, "fields": meta},
        sources=["TRF_TREND", "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.TRAFFIC_SOURCES, cv.units_note(units)],
        decoded=True,
        page=page,
        total_count=len(all_rows),
        returned=len(shown),
    )


def get_truck_volume_parameters(
    state: str, shrp_id: str, vehicle_class: int | None = None, units: Units = "stored"
) -> Envelope:
    """MEPDG truck-volume inputs for a section: for each experiment and vehicle class (4-13), the traffic
    opening date, last year, AADTT in the first year of the LTPP lane, the class's share of trucks (percent),
    and the growth function (e.g. compound) and growth rate (percent per year) with a use rating that says
    how good the basis is. vehicle_class: keep one class."""
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = [Cond("VEHICLE_CLASS", "eq", vehicle_class)] if vehicle_class is not None else []
    rows, meta, _ = read_section_rows(
        repo, "MEPDG_TRUCK_VOL_PARAMETERS", ref, extra=extra,
        order_by=[("TRAFFIC_OPEN_YEAR_EXP_NO", False), ("VEHICLE_CLASS", False)], units=units, drop=DROP,
    )  # fmt: skip
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("No MEPDG truck-volume parameters exist for this section.")
    return respond(
        {"section": ref.key(), "parameters": rows, "fields": meta},
        sources=["MEPDG_TRUCK_VOL_PARAMETERS", "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def get_axles_per_truck(
    state: str, shrp_id: str, vehicle_class: int | None = None, units: Units = "stored"
) -> Envelope:
    """Average number of single, tandem, tridem and quad axles per truck, by FHWA vehicle class (4-13), as
    used for MEPDG design, with a use rating for the quality of the data. vehicle_class: keep one class."""
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = [Cond("VEHICLE_CLASS", "eq", vehicle_class)] if vehicle_class is not None else []
    rows, meta, _ = read_section_rows(
        repo,
        "MEPDG_AXLE_PER_TRUCK",
        ref,
        extra=extra,
        order_by=[("VEHICLE_CLASS", False)],
        units=units,
        drop=DROP,
    )
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("No axles-per-truck record exists for this section.")
    return respond(
        {"section": ref.key(), "axles_per_truck": rows, "fields": meta},
        sources=["MEPDG_AXLE_PER_TRUCK", "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def get_axle_load_distribution(
    state: str,
    shrp_id: str,
    axle_group: Literal["single", "tandem", "tridem", "quad"] | None = None,
    month: int | None = None,
    vehicle_class: int | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Axle load distribution factors (MEPDG): the percentage of axles in each of 39 load bins, by axle group,
    month and FHWA vehicle class (4-13). Each row has `load_group_pct`, a list of 39 percentages (bin 1 to
    39, summing to 100 in `total`) and a use rating for data quality. Bin 1 covers 0-2,999 lb for single
    axles, 0-5,999 lb for tandem axles and 0-11,999 lb for tridem and quad axles; later bins are 1,000 lb
    (single), 2,000 lb (tandem) or 3,000 lb (tridem and quad) wide, and bin 39 is 40,000-40,999 lb for
    singles and 80,000-81,999 lb for tandems. axle_group, month (1-12) and vehicle_class narrow the rows
    (a section has up to 480). limit / offset: page through rows (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    extra: list[Cond] = []
    if axle_group is not None:
        extra.append(Cond("AXLE_GROUP", "eq", {"single": 1, "tandem": 2, "tridem": 3, "quad": 4}[axle_group]))
    if month is not None:
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12.")
        extra.append(Cond("MONTH", "eq", month))
    if vehicle_class is not None:
        extra.append(Cond("VEHICLE_CLASS", "eq", vehicle_class))
    rows, meta, total = read_section_rows(
        repo, "MEPDG_AXLE_LOAD_DIST_FACTOR", ref, extra=extra,
        order_by=[("AXLE_GROUP", False), ("MONTH", False), ("VEHICLE_CLASS", False)],
        page=page, units="stored", drop=DROP,
    )  # fmt: skip
    for r in rows:
        bins = [r.pop(k, None) for k in sorted(k for k in list(r) if re.fullmatch(r"mepdg_lg\d\d", k))]
        r["load_group_pct"] = bins
        r.pop("month_name", None)
    return respond(
        {"section": ref.key(), "rows": rows, "fields": meta},
        sources=["MEPDG_AXLE_LOAD_DIST_FACTOR", "LDW_DP_GENERAL"],
        caveats=[
            cv.SECTION_KEY,
            "Load-group percentages are as stored; each row's bins sum to `total` (100%).",
        ],
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


_ADJUSTMENT_TABLES = ("TRF_MEPDG_MONTH_ADJ_FACTR", "TRF_MEPDG_HOURLY_DIST")


def _adjustment_site(state: str, shrp_id: str) -> tuple[SectionRef, str]:
    """Resolve the site whose adjustment factors to read: (site, note).

    Hourly (and some monthly) factors are kept for the virtual SPS project site (SHRP_ID ending in 00,
    e.g. 0100), which is not a test section. So: a real section is used as is when it has factors; else
    its project site (first two characters + 00) is used; a virtual site can also be asked for directly.
    """
    repo = get_repository()
    code = resolve_state(state)
    ident = normalize_shrp_id(shrp_id)

    def has_rows(sid: str) -> bool:
        return sum(repo.dataset_counts(code, sid, list(_ADJUSTMENT_TABLES)).values()) > 0

    try:
        ref = resolve_section(repo, state, shrp_id)
    except ValueError:
        if has_rows(ident):
            site = SectionRef(code, state_name(code) or state, ident, {})
            return site, f"{ident} is a virtual SPS project site, not a test section."
        raise
    if has_rows(ref.shrp_id):
        return ref, ""
    project = ref.shrp_id[:2] + "00"
    if project != ref.shrp_id and has_rows(project):
        site = SectionRef(code, ref.state, project, {})
        return (
            site,
            f"Section {ref.shrp_id} has no adjustment factors of its own; showing its SPS project site {project}.",
        )
    return ref, ""


def get_traffic_adjustment_factors(
    state: str,
    shrp_id: str,
    kind: Literal["monthly", "hourly", "both"] = "both",
    start_year: int | None = None,
    end_year: int | None = None,
    vehicle_class: int | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Traffic adjustment factors for MEPDG: monthly ratios by year, month and FHWA vehicle class (kind
    "monthly"), and the hourly distribution of traffic by year and hour of day with adjustment factors
    (kind "hourly"). Default "both". vehicle_class applies to monthly factors. start_year / end_year window.
    Hourly factors, and some monthly ones, are recorded for the virtual SPS project site (SHRP_ID ending in
    00, such as 0100) rather than for individual sections: pass that ID directly, or pass a section and
    its project site is used when the section has none (the result says which site it read).
    limit / offset page each list separately (page size capped at 50; use next_offset)."""
    repo = get_repository()
    ref, site_note = _adjustment_site(state, shrp_id)
    page = Page.of(limit, offset)
    year_conds: list[Cond] = []
    if start_year is not None:
        year_conds.append(Cond("YEAR", "ge", start_year))
    if end_year is not None:
        year_conds.append(Cond("YEAR", "le", end_year))
    data: dict[str, Any] = {"section": ref.key()}
    metas: list[dict[str, dict[str, Any]]] = []
    sources = ["LDW_DP_GENERAL"]
    totals: list[int] = []
    if site_note:
        data["site_note"] = site_note
    if kind in ("monthly", "both"):
        extra = year_conds + ([Cond("VEHICLE_CLASS", "eq", vehicle_class)] if vehicle_class is not None else [])
        rows, meta, total = read_section_rows(
            repo, "TRF_MEPDG_MONTH_ADJ_FACTR", ref, extra=extra,
            order_by=[("YEAR", True), ("MONTH", False), ("VEHICLE_CLASS", False)], page=page, drop=DROP,
        )  # fmt: skip
        data["monthly"] = rows
        metas.append(meta)
        sources.append("TRF_MEPDG_MONTH_ADJ_FACTR")
        totals.append(total)
    if kind in ("hourly", "both"):
        rows, meta, total = read_section_rows(
            repo, "TRF_MEPDG_HOURLY_DIST", ref, extra=year_conds,
            order_by=[("YEAR", True), ("HOUR", False)], page=page, drop=DROP,
        )  # fmt: skip
        data["hourly"] = rows
        metas.append(meta)
        sources.append("TRF_MEPDG_HOURLY_DIST")
        totals.append(total)
    data["fields"] = fields.merge_fields(*metas)
    notes = [cv.SECTION_KEY] + ([site_note] if site_note else [])
    if not any(data.get(k) for k in ("monthly", "hourly")):
        notes.append("No traffic adjustment factors exist for this section with these options.")
    return respond(
        data,
        sources=sources,
        caveats=notes,
        decoded=True,
        page=page,
        total_count=max(totals) if totals else 0,
        returned=max((len(data.get(k, [])) for k in ("monthly", "hourly")), default=0),
    )


def register(mcp: FastMCP) -> None:
    for tool in (
        get_traffic_summary,
        get_traffic_trend,
        get_truck_volume_parameters,
        get_axles_per_truck,
        get_axle_load_distribution,
        get_traffic_adjustment_factors,
    ):
        mcp.tool()(tool)
