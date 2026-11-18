"""Sections: search_sections, get_section_profile, summarize_sections_by_group."""

from typing import Any

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.kb import table_group
from infopave_mcp.models import Envelope, Page, SectionFilter
from infopave_mcp.models.inputs import (
    ClimateZone,
    GpsSps,
    MonitoringStatus,
    Region,
    SectionGroupBy,
    TopLayer,
    Units,
)
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.services.topics import key_for_table, public_title

SECTIONS = "LDW_DP_GENERAL"

# How the section record is grouped in get_section_profile.
_PROFILE_GROUPS: dict[str, tuple[str, ...]] = {
    "identification": ("ldw_section_id", "state_name", "state_code", "shrp_id", "region_des", "region_code"),
    "location": (
        "county_name", "route_detail", "route_no", "direction_detail", "mile_post", "latitude", "longitude",
        "location_info",
    ),
    "roadway": ("func_class_detail", "no_of_lanes", "lane_width", "section_length"),
    "experiment": (
        "experiment_type_detail", "current_experiment_type", "gps_sps", "all_section_expirement",
        "top_layer_type_code",
    ),
    "climate": ("climatic_region_detail", "climatic_zone"),
    "dates": (
        "date_of_construction", "date_start_ltpp_section", "date_inactive", "ltpp_monitoring_status_det",
        "date_added", "date_updated",
    ),
}  # fmt: skip


def search_sections(
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
    near_latitude: float | None = None,
    near_longitude: float | None = None,
    radius_km: float = 25,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Find LTPP test sections. All filters are optional and combined with AND.

    state: name (Ohio), postal abbreviation (OH) or numeric code (39).
    region: LTPP region (North Atlantic, North Central, Southern, Western).
    climate_zone: wet-freeze, wet-no-freeze, dry-freeze or dry-no-freeze.
    experiment: part of an experiment name (e.g. "JPCP", "AC Overlay"), an experiment code, or an SPS
        project such as "SPS-5".
    gps_sps: GPS (general pavement study) or SPS (specific pavement study).
    top_layer: AC (asphalt concrete surface) or PCC (Portland cement concrete surface).
    functional_class: part of the road class name, e.g. "Interstate" or "Rural Minor Arterial".
    monitoring_status: active, or out-of-study.
    county: part of a county name. constructed_after / constructed_before: construction year range.
    near_latitude + near_longitude: sections within radius_km (default 25), nearest first.
    limit / offset: page through results (page size capped at 50; use next_offset).
    """
    f = SectionFilter.create(
        state=state, region=region, climate_zone=climate_zone, experiment=experiment, gps_sps=gps_sps,
        top_layer=top_layer, functional_class=functional_class, monitoring_status=monitoring_status,
        county=county, constructed_after=constructed_after, constructed_before=constructed_before,
        near_latitude=near_latitude, near_longitude=near_longitude, radius_km=radius_km,
    )  # fmt: skip
    page = Page.of(limit, offset)
    rows, total = get_repository().search_sections(f, page)
    notes = [cv.SECTION_KEY] + ([cv.DISTANCE_NOTE] if f.has_near else [])
    return respond(rows, sources=[SECTIONS], caveats=notes, page=page, total_count=total, returned=len(rows))


def get_section_profile(state: str, shrp_id: str, units: Units = "stored") -> Envelope:
    """One test section's general facts, and which datasets hold data for it.

    state: name, postal abbreviation or numeric code. shrp_id: the section's SHRP_ID (e.g. "0207").
    Returns identification, location, roadway, experiment, climate zone and dates, plus a list of every
    dataset (materials, performance, climate, traffic, maintenance...) with the number of rows it holds for
    this section, so you know which other tools will return something.
    units: stored (default), us or si.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    rows, meta = fields.shape(repo, SECTIONS, [ref.record], units)
    record = rows[0]

    profile: dict[str, Any] = {}
    used: set[str] = set()
    for group, cols in _PROFILE_GROUPS.items():
        block = {c: record[c] for c in cols if c in record and record[c] is not None}
        if block:
            profile[group] = block
            used.update(block)
    other = {k: v for k, v in record.items() if k not in used and v is not None}
    if other:
        profile["other"] = other

    tables = repo.section_tables()
    counts = repo.dataset_counts(ref.state_code, ref.shrp_id, tables)
    datasets: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        n = counts.get(table, 0)
        if n:
            datasets.setdefault(table_group(table), []).append(
                {"topic": key_for_table(table), "title": public_title(table), "rows": n}
            )
    data = {
        "section": ref.key(),
        "profile": profile,
        "datasets": datasets,
        "fields": {k: v for k, v in meta.items() if k in record},
    }
    return respond(
        data,
        sources=[SECTIONS, *tables],
        caveats=[cv.SECTION_KEY, cv.units_note(units)],
        decoded=True,
    )


def summarize_sections_by_group(
    group_by: SectionGroupBy,
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
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Count test sections by a grouping.

    group_by: state, region, climate_zone, experiment_type, sps_project, gps_sps, top_layer (pavement
        surface), functional_class, monitoring_status, construction_decade, county or lanes.
    The same optional filters as search_sections narrow which sections are counted (for example
    group_by="climate_zone" with state="Texas" counts Texas sections by climate zone).
    Each group reports sections, share of all matching sections, how many are active or out-of-study, and
    the earliest and latest construction year. `totals` covers every matching section, not only this page.
    limit / offset: page through groups (page size capped at 50; use next_offset).
    """
    f = SectionFilter.create(
        state=state, region=region, climate_zone=climate_zone, experiment=experiment, gps_sps=gps_sps,
        top_layer=top_layer, functional_class=functional_class, monitoring_status=monitoring_status,
        county=county, constructed_after=constructed_after, constructed_before=constructed_before,
    )  # fmt: skip
    page = Page.of(limit, offset)
    groups, total_groups, totals = get_repository().group_sections(group_by, f, page)
    return respond(
        {"group_by": group_by, "totals": totals, "groups": groups},
        sources=[SECTIONS],
        caveats=[cv.SECTION_KEY],
        page=page,
        total_count=total_groups,
        returned=len(groups),
    )


def register(mcp: FastMCP) -> None:
    mcp.tool()(search_sections)
    mcp.tool()(get_section_profile)
    mcp.tool()(summarize_sections_by_group)
