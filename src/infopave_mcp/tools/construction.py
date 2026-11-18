"""Construction features (ARCFD): get_drainage_features, get_joint_features, get_shoulder_features."""

from typing import Any

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Cond, Envelope, Page, make_range
from infopave_mcp.models.inputs import Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.readers import read_section_rows
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section

DROP = ("state_code", "shrp_id", "record_status", "data_rec_id")


def get_drainage_features(
    state: str, shrp_id: str, construction_no: int | None = None, units: Units = "stored"
) -> Envelope:
    """Drainage design of a section: drainage type and location, pipe type and diameter, filter type and
    permeability, subdrain purpose and spacing, hydraulic gradient and conductivity, cross slope and grade.
    Only non-empty values are shown. construction_no narrows to one construction event."""
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    rows, meta, _ = read_section_rows(
        repo, "ANALYSIS_DRAINAGE", ref, construction_no=construction_no,
        order_by=[("CONSTRUCTION_NO", False)], units=units, drop=DROP,
    )  # fmt: skip
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("No drainage record exists for this section.")
    return respond(
        {"section": ref.key(), "drainage": [fields.compact(r) for r in rows], "fields": meta},
        sources=["ANALYSIS_DRAINAGE", "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def get_joint_features(state: str, shrp_id: str, layer_no: int | None = None, units: Units = "stored") -> Envelope:
    """Joint design of a concrete section: how joints were formed and sealed, saw-cut depth, joint spacing
    and skew, dowel diameter/length/spacing/coating, and tie-bar details. Only non-empty values are shown.
    Asphalt sections have no joint record, so an empty result is normal for them."""
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = [Cond("LAYER_NO", "eq", layer_no)] if layer_no is not None else []
    rows, meta, _ = read_section_rows(
        repo, "ANALYSIS_JOINT", ref, extra=extra, order_by=[("LAYER_NO", False)], units=units, drop=DROP
    )
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("No joint record exists for this section (joints apply to jointed concrete pavements).")
    return respond(
        {"section": ref.key(), "joints": [fields.compact(r) for r in rows], "fields": meta},
        sources=["ANALYSIS_JOINT", "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def get_shoulder_features(
    state: str,
    shrp_id: str,
    start: int | str | None = None,
    end: int | str | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Shoulder type, width, thickness and condition of a section over time.

    Each row is a survey: inside (I_) and outside (O_) shoulder base and surface types, thicknesses and
    widths, paving, joints, plus condition (dropoff, separation, sealing) and any shoulder restoration.
    start / end: a year (2005) or date (2005-06-30) window on the survey date. Newest survey first.
    limit / offset: page through surveys (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    rows, meta, total = read_section_rows(
        repo, "ANALYSIS_SHOULDER", ref, date_column="SURVEY_DATE", dates=make_range(start, end),
        order_by=[("SURVEY_DATE", True), ("POINT_LOC", False)], page=page, units=units, drop=DROP,
    )  # fmt: skip
    data: dict[str, Any] = {
        "section": ref.key(),
        "surveys": [fields.compact(r) for r in rows],
        "fields": meta,
    }
    return respond(
        data,
        sources=["ANALYSIS_SHOULDER", "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.units_note(units)],
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def register(mcp: FastMCP) -> None:
    mcp.tool()(get_drainage_features)
    mcp.tool()(get_joint_features)
    mcp.tool()(get_shoulder_features)
