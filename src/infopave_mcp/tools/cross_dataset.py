"""Cross-dataset tools: find_sections_across_datasets and get_section_report."""

from typing import Any

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Envelope, Page, SectionFilter
from infopave_mcp.models.inputs import ClimateZone, GpsSps, MonitoringStatus, Region, TopLayer, Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import treatments
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.tools import climate, maintenance, materials, performance, sections, traffic


def _is_empty(value: Any) -> bool:
    """True for nothing, or a mapping/list whose every entry is itself nothing."""
    if value is None or value == [] or value == {}:
        return True
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return False


def find_sections_across_datasets(
    state: str | None = None,
    region: Region | None = None,
    climate_zone: ClimateZone | None = None,
    experiment: str | None = None,
    gps_sps: GpsSps | None = None,
    top_layer: TopLayer | None = None,
    functional_class: str | None = None,
    monitoring_status: MonitoringStatus | None = None,
    county: str | None = None,
    constructed_after: int | None = None,
    constructed_before: int | None = None,
    min_mean_annual_precipitation_mm: float | None = None,
    max_mean_annual_precipitation_mm: float | None = None,
    min_mean_freeze_index: float | None = None,
    max_mean_freeze_index: float | None = None,
    min_mean_annual_air_temp_c: float | None = None,
    max_mean_annual_air_temp_c: float | None = None,
    climate_start_year: int | None = None,
    climate_end_year: int | None = None,
    min_ac_thickness_in: float | None = None,
    max_ac_thickness_in: float | None = None,
    min_pcc_thickness_in: float | None = None,
    max_pcc_thickness_in: float | None = None,
    min_aadtt: int | None = None,
    max_aadtt: int | None = None,
    treatment: int | str | list[int | str] | None = None,
    treated_after: int | None = None,
    treated_before: int | None = None,
    min_latest_mri: float | None = None,
    max_latest_mri: float | None = None,
    min_latest_rut_mm: float | None = None,
    max_latest_rut_mm: float | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Find test sections that satisfy conditions on several datasets at once. All conditions are optional
    and combined with AND; each condition used adds its value as a column so you can see why a section matched.

    Section: state, region, climate_zone, experiment, gps_sps, top_layer, functional_class,
        monitoring_status, county, constructed_after / constructed_before (same as search_sections).
    Climate (MERRA-2 averages over climate_start_year..climate_end_year, default 1980-2025):
        min/max_mean_annual_precipitation_mm, min/max_mean_freeze_index (deg C degree days),
        min/max_mean_annual_air_temp_c.
    Materials: min/max_ac_thickness_in (total asphalt thickness in the section's latest structure that has
        asphalt layers), min/max_pcc_thickness_in (concrete layer thickness, latest structure).
    Traffic: min/max_aadtt (highest representative AADTT recorded for the section).
    Treatments: treatment (code 19, word "overlay" or a list) with optional treated_after /
        treated_before years; the section must have at least one matching treatment.
    Performance: min/max_latest_mri (m/km, latest unflagged roughness visit), min/max_latest_rut_mm (mm,
        latest unflagged maximum rut depth).
    Example: wet-freeze sections with at least 6 in of asphalt that had an overlay and whose latest
    roughness is above 2 m/km. limit / offset: page through sections (page size capped at 50).
    """
    repo = get_repository()
    f = SectionFilter.create(
        state=state, region=region, climate_zone=climate_zone, experiment=experiment, gps_sps=gps_sps,
        top_layer=top_layer, functional_class=functional_class, monitoring_status=monitoring_status,
        county=county, constructed_after=constructed_after, constructed_before=constructed_before,
    )  # fmt: skip
    page = Page.of(limit, offset)
    criteria: dict[str, Any] = {
        "min_mean_annual_precipitation_mm": min_mean_annual_precipitation_mm,
        "max_mean_annual_precipitation_mm": max_mean_annual_precipitation_mm,
        "min_mean_freeze_index": min_mean_freeze_index,
        "max_mean_freeze_index": max_mean_freeze_index,
        "min_mean_annual_air_temp_c": min_mean_annual_air_temp_c,
        "max_mean_annual_air_temp_c": max_mean_annual_air_temp_c,
        "climate_start_year": climate_start_year,
        "climate_end_year": climate_end_year,
        "min_ac_thickness_in": min_ac_thickness_in,
        "max_ac_thickness_in": max_ac_thickness_in,
        "min_pcc_thickness_in": min_pcc_thickness_in,
        "max_pcc_thickness_in": max_pcc_thickness_in,
        "min_aadtt": min_aadtt,
        "max_aadtt": max_aadtt,
        "maint_codes": treatments.resolve_treatments(repo, treatment),
        "treated_after": f"{treated_after}-01-01" if treated_after else None,
        "treated_before": f"{treated_before}-12-31" if treated_before else None,
        "min_latest_mri": min_latest_mri,
        "max_latest_mri": max_latest_mri,
        "min_latest_rut_mm": min_latest_rut_mm,
        "max_latest_rut_mm": max_latest_rut_mm,
    }
    for lo, hi in (
        ("min_mean_annual_precipitation_mm", "max_mean_annual_precipitation_mm"),
        ("min_mean_freeze_index", "max_mean_freeze_index"),
        ("min_mean_annual_air_temp_c", "max_mean_annual_air_temp_c"),
        ("min_ac_thickness_in", "max_ac_thickness_in"),
        ("min_pcc_thickness_in", "max_pcc_thickness_in"),
        ("min_aadtt", "max_aadtt"),
        ("min_latest_mri", "max_latest_mri"),
        ("min_latest_rut_mm", "max_latest_rut_mm"),
    ):
        if criteria[lo] is not None and criteria[hi] is not None and criteria[lo] > criteria[hi]:
            raise ValueError(f"{lo} must not be greater than {hi}.")
    rows, total = repo.find_sections(criteria, f, page)

    used = {k for k, v in criteria.items() if v is not None}
    sources = ["LDW_DP_GENERAL"]
    notes = [cv.SECTION_KEY]
    if used & {"min_mean_annual_precipitation_mm", "max_mean_annual_precipitation_mm", "min_mean_freeze_index",
               "max_mean_freeze_index", "min_mean_annual_air_temp_c", "max_mean_annual_air_temp_c"}:  # fmt: skip
        sources += ["MERRA_GRID_SECTION", "MERRA_PRECIP_YEAR", "MERRA_TEMP_YEAR"]
        notes += [cv.CLIMATE_SCOPE, cv.CLIMATE_MODELLED]
    if used & {"min_ac_thickness_in", "max_ac_thickness_in"}:
        sources += ["ANALYSIS_TST_AC", "ANALYSIS_TST_ACT"]
        notes.append(cv.CONSTRUCTION_BASIS)
    if used & {"min_pcc_thickness_in", "max_pcc_thickness_in"}:
        sources.append("ANALYSIS_TST_PCC")
    if used & {"min_aadtt", "max_aadtt"}:
        sources.append("TRF_REP")
        notes.append(cv.REPRESENTATIVE_TRAFFIC)
    if criteria["maint_codes"]:
        sources.append("ANALYSIS_MNT_RHB_SUMMARY")
    if used & {"min_latest_mri", "max_latest_mri"}:
        sources.append("ANALYSIS_IRI")
    if used & {"min_latest_rut_mm", "max_latest_rut_mm"}:
        sources.append("ANALYSIS_RUTTING")
    if used & {"min_latest_mri", "max_latest_mri", "min_latest_rut_mm", "max_latest_rut_mm"}:
        notes.append("Latest performance uses the most recent visit or survey with an unflagged value.")
    return respond(
        {
            "sections": rows,
            "conditions_used": sorted(used | ({"section filters"} if not f.is_empty() else set())),
        },
        sources=sources,
        caveats=notes,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def get_section_report(state: str, shrp_id: str, units: Units = "stored") -> Envelope:
    """A one-call summary of everything known about a test section: general facts, which datasets exist,
    the latest pavement structure, latest roughness, rutting, cracking and load transfer with their trends,
    representative traffic, average climate, and the maintenance and rehabilitation history.

    Use it first for an overview; call the specific tools (get_roughness_history, get_layer_structure,
    get_treatment_history, ...) for the detail behind any part. units: stored, us or si.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    s, i = ref.state, ref.shrp_id
    parts: dict[str, Any] = {"section": ref.key()}
    sources: list[str] = []
    notes: list[str] = []
    missing: list[str] = []

    def take(name: str, call: Any, pick: Any = lambda d: d) -> None:
        try:
            env = call()
        except ValueError as exc:
            missing.append(f"{name}: {exc}")
            return
        value = pick(env.data)
        if _is_empty(value):
            missing.append(f"{name}: no data")
            return
        parts[name] = value
        sources.extend(env.sources)
        notes.extend(env.caveats)

    take(
        "profile",
        lambda: sections.get_section_profile(s, i, units),
        lambda d: {"profile": d["profile"], "datasets": d["datasets"]},
    )

    def latest_structure(d: dict[str, Any]) -> dict[str, Any] | None:
        events = d["construction_events"]
        if not events:
            return None
        ev = events[-1]  # highest construction number = current structure
        return {
            "construction_no": ev["construction_no"], "total_thickness": ev["total_thickness"],
            "asphalt_thickness": ev["asphalt_thickness"], "concrete_thickness": ev["concrete_thickness"],
            "construction_events": len(events),
            "layers": [
                {k: layer.get(k) for k in ("layer_no", "layer_type", "layer_type_name", "repr_thickness", "matl_code_name")}
                for layer in ev["layers"]
            ],
        }  # fmt: skip

    take("latest_structure", lambda: materials.get_layer_structure(s, i, None, units), latest_structure)
    take(
        "roughness",
        lambda: performance.get_roughness_history(s, i, limit=1, units=units),
        lambda d: {"summary": d["summary"], "latest_visit": (d["visits"] or [None])[0]},
    )
    take(
        "rutting",
        lambda: performance.get_rutting_history(s, i, limit=1, units=units),
        lambda d: {"summary": d["summary"], "latest_survey": (d["surveys"] or [None])[0]},
    )
    take(
        "cracking",
        lambda: performance.get_cracking_history(s, i, limit=1, units=units),
        lambda d: {
            k: {
                "headline_measure": v["headline_measure"],
                "trend": v["trend"],
                "latest_survey": (v["surveys"] or [None])[0],
            }
            for k, v in d["distress"].items()
        },
    )
    take(
        "load_transfer",
        lambda: performance.get_load_transfer_history(s, i, limit=1),
        lambda d: {"summary": d["summary"], "latest_test": (d["tests"] or [None])[0]},
    )
    take(
        "traffic",
        lambda: traffic.get_traffic_summary(s, i, "summary", units),
        lambda d: d["representative_traffic"],
    )
    take(
        "climate_period_means",
        lambda: climate.get_section_climate_annual(s, i, ["temperature", "precipitation"], limit=1, units=units),
        lambda d: {"grid_cell": d["grid_cell"], "means": d["period_means"], "years": d["years_in_period"]},
    )

    def treatment_summary(d: dict[str, Any]) -> dict[str, Any]:
        rows = d["treatments"]
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r["treatment"]] = by_type.get(r["treatment"], 0) + 1
        return {
            "treatments": len(rows),
            "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
            "latest": [
                {k: r.get(k) for k in ("imp_date", "maint_work", "treatment", "construction_no")} for r in rows[-5:]
            ],
        }

    take(
        "maintenance_and_rehabilitation",
        lambda: maintenance.get_treatment_history(s, i, limit=50),
        treatment_summary,
    )
    if missing:
        parts["not_available"] = missing
    return respond(
        parts,
        sources=sources or ["LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def register(mcp: FastMCP) -> None:
    mcp.tool()(find_sections_across_datasets)
    mcp.tool()(get_section_report)
