"""Performance (ARPED): roughness, rutting, cracking, load transfer, dowel scans and group comparisons."""

from typing import Any, Literal

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Aggregate, Cond, Envelope, Page, SectionFilter, Select, make_range
from infopave_mcp.models.inputs import (
    PAVEMENT_CLASSES,
    ClimateZone,
    GpsSps,
    Measure,
    PavementClass,
    Region,
    TopLayer,
    Units,
)
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.measures import MEASURES
from infopave_mcp.services.performance import merge_flags, trend_summary
from infopave_mcp.services.readers import date_conds, read_section_rows, section_conds
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.services.topics import public_title
from infopave_mcp.services.units import conversion_for, convert_number

IRI = "ANALYSIS_IRI"
RUTTING = "ANALYSIS_RUTTING"
LTE = "ANALYSIS_LTE"
MIT = "ANALYSIS_MIT"
DROP = ("state_code", "shrp_id", "record_status", "data_rec_id")

_IRI_VALUES = ["IRI_LEFT_WHEEL_PATH", "IRI_RIGHT_WHEEL_PATH", "IRI_CENTER_LANE", "MRI"]
_IRI_FLAGS = ["IRI_LEFT_WHEEL_PATH_FLAG", "IRI_RIGHT_WHEEL_PATH_FLAG", "IRI_CENTER_LANE_FLAG", "MRI_FLAG"]
_RUT_VALUES = [
    "LLH_DEPTH_1_8_MEAN", "RLH_DEPTH_1_8_MEAN", "MAX_MEAN_DEPTH_1_8",
    "LLH_DEPTH_WIRE_REF_MEAN", "RLH_DEPTH_WIRE_REF_MEAN", "MAX_MEAN_DEPTH_WIRE_REF",
]  # fmt: skip
_RUT_FLAGS = [c + "_FLAG" for c in _RUT_VALUES]

# Distress tables by pavement type, with the columns shown in `summary` detail and the headline measure.
_DISTRESS: dict[str, dict[str, Any]] = {
    "asphalt": {
        "table": "ANALYSIS_DIS_AC",
        "headline": "mepdg_cracking_percent_ac",
        "summary": [
            "hpms16_cracking_percent_ac", "mepdg_cracking_percent_ac", "me_percent_wheel_path_crack",
            "mepdg_long_crack_length_ac", "mepdg_trans_crack_length_ac", "gator_crack_a", "blk_crack_a",
            "long_crack_wp_l", "trans_crack_no", "patch_a", "potholes_a", "raveling", "bleeding",
        ],
    },
    "jointed_concrete": {
        "table": "ANALYSIS_DIS_JPCC",
        "headline": "mepdg_cracking_percent_jpcc",
        "summary": [
            "hpms16_cracking_percent_jpcc", "mepdg_cracking_percent_jpcc", "me_percent_cracked_slabs",
            "cracked_slabs_total", "slab_count", "trans_crack_no", "long_crack_l", "corner_breaks_no",
            "avg_edge_fault", "avg_wheelpath_fault", "patch_flex_a", "patch_rigid_a", "scaling_a",
            "trans_spalling_l", "long_spalling_l",
        ],
    },
    "crcp": {
        "table": "ANALYSIS_DIS_CRCP",
        "headline": "mepdg_punchouts_crcp",
        "summary": [
            "hpms16_cracking_percent_crcp", "mepdg_punchouts_crcp", "punchouts_no", "trans_crack_no",
            "long_crack_l", "patch_flex_a", "patch_rigid_a", "long_spalling_l",
        ],
    },
}  # fmt: skip

PerfGroupBy = Literal[
    "pavement_family", "pavement_class", "climate_zone", "region", "state", "experiment_type",
    "top_layer", "functional_class", "gps_sps", "none",
]  # fmt: skip


def _page_rows(rows: list[dict[str, Any]], page: Page) -> list[dict[str, Any]]:
    return rows[page.offset : page.offset + page.limit]


def _series(
    state: str, shrp_id: str, table: str, group: list[str], avg: list[str], flags: list[str],
    date_col: str, value_key: str, construction_no: int | None, start: int | str | None,
    end: int | str | None, exclude_flagged: bool, units: str, limit: int, offset: int,
    minmax: list[str] | None = None, extra: list[Cond] | None = None, order_desc: bool = False,
    count_name: str = "records",
) -> tuple[Any, list[dict[str, Any]], dict[str, Any], dict[str, Any] | None, int, Page]:  # fmt: skip
    """Shared by roughness, rutting and load transfer: aggregate a section's series, summarise, page."""
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    where = section_conds(ref) + (extra or [])
    if construction_no is not None and repo.has_column(table, "CONSTRUCTION_NO"):
        where.append(Cond("CONSTRUCTION_NO", "eq", construction_no))
    where += date_conds(date_col, make_range(start, end))
    if exclude_flagged:
        where += [Cond(c, "isnull") for c in flags]
    rows, total = repo.aggregate(
        Aggregate(
            table=table,
            group_by=group,
            avg=avg,
            minmax=minmax or [],
            flags=flags,
            where=where,
            order_by=[(date_col, order_desc)],
        )  # fmt: skip
    )
    for r in rows:
        r[count_name] = r.pop("n_rows")
    shaped, meta = fields.shape(repo, table, rows, units)
    meta.update(merge_flags(repo, table, shaped, [c.lower() for c in flags]))
    summary = trend_summary(shaped, date_col.lower(), value_key)
    return ref, shaped, meta, summary, total, page


def get_roughness_history(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    by_run: bool = False,
    exclude_flagged: bool = False,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """International Roughness Index (IRI) and Mean Roughness Index (MRI) of a section by profiler visit.

    Each row is a visit: IRI for the left and right wheel paths and the lane centre, and MRI (the average
    of the two wheel paths), averaged over the visit's runs, with the number of runs and any flags. IRI is
    stored in m/km; units="us" gives in/mi. A `summary` gives the first, latest and peak MRI and the change
    per year. by_run=true returns individual runs instead. exclude_flagged=true drops runs LTPP flagged as
    possible anomalies. start / end: a year (2005) or date (2005-06-30). construction_no: one construction
    event. Newest visit first. limit / offset: page through visits (page size capped at 50).
    """
    repo = get_repository()
    if by_run:
        ref = resolve_section(repo, state, shrp_id)
        page = Page.of(limit, offset)
        extra = [Cond(c, "isnull") for c in _IRI_FLAGS] if exclude_flagged else []
        rows, meta, total = read_section_rows(
            repo, IRI, ref, construction_no=construction_no, extra=extra, date_column="VISIT_DATE",
            dates=make_range(start, end), order_by=[("VISIT_DATE", True), ("RUN_NUMBER", False)],
            page=page, units=units, drop=DROP,
        )  # fmt: skip
        summary = None
    else:
        ref, rows, meta, summary, total, page = _series(
            state, shrp_id, IRI, ["VISIT_DATE", "VISIT_NO", "CONSTRUCTION_NO", "PAVEMENT_FAMILY"], _IRI_VALUES,
            _IRI_FLAGS, "VISIT_DATE", "mri", construction_no, start, end, exclude_flagged, units,
            limit, offset, order_desc=True, count_name="runs",
        )  # fmt: skip
        rows = _page_rows(rows, page)
    notes = [cv.SECTION_KEY, cv.IRI_RUNS, cv.units_note(units)]
    if any(r.get("flags") for r in rows):
        notes.append(cv.FLAGS)
    return respond(
        {"section": ref.key(), "summary": summary, "visits": rows, "fields": meta},
        sources=[IRI, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def get_rutting_history(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    exclude_flagged: bool = False,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Rut depth of a section by survey: mean depth in the left and right wheel paths and the maximum of the
    two, measured with a 1.8 m straightedge (_1_8) and with a wire reference, in mm as stored (units="us"
    gives inches), with flags. A `summary` gives the first, latest and peak maximum rut depth and the change
    per year. start / end: a year or date. construction_no: one construction event. Newest survey first.
    limit / offset: page through surveys (page size capped at 50).
    """
    ref, rows, meta, summary, total, page = _series(
        state, shrp_id, RUTTING, ["SURVEY_DATE", "VISIT_NO", "CONSTRUCTION_NO", "PAVEMENT_FAMILY"], _RUT_VALUES,
        _RUT_FLAGS, "SURVEY_DATE", "max_mean_depth_1_8", construction_no, start, end, exclude_flagged, units,
        limit, offset, order_desc=True, count_name="runs",
    )  # fmt: skip
    rows = _page_rows(rows, page)
    notes = [cv.SECTION_KEY, cv.units_note(units)] + ([cv.FLAGS] if any(r.get("flags") for r in rows) else [])
    return respond(
        {"section": ref.key(), "summary": summary, "surveys": rows, "fields": meta},
        sources=[RUTTING, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def get_cracking_history(
    state: str,
    shrp_id: str,
    pavement_type: Literal["auto", "asphalt", "jointed_concrete", "crcp"] = "auto",
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    detail: Literal["summary", "full"] = "summary",
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
) -> Envelope:
    """Cracking and distress of a section by manual survey.

    Distress is stored in three tables by pavement type: asphalt (fatigue, block, longitudinal, transverse
    cracking, patching, potholes, raveling), jointed concrete (cracked slabs, transverse and longitudinal
    cracking, corner breaks, faulting, spalling) and CRCP (punchouts). pavement_type="auto" returns every
    table that has data for the section. detail="summary" shows the main measures; "full" every non-empty
    column and flag. A `trend` follows the headline measure (MEPDG cracking %, or punchouts per mile for
    CRCP). start / end: a year or date. limit: surveys per table, newest first (at most 50).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, 0)
    kinds = list(_DISTRESS) if pavement_type == "auto" else [pavement_type]
    rng = make_range(start, end)
    out: dict[str, Any] = {}
    metas: list[dict[str, dict[str, Any]]] = []
    sources = ["LDW_DP_GENERAL"]
    for kind in kinds:
        spec = _DISTRESS[kind]
        table = spec["table"]
        cols = None
        if detail == "summary":
            wanted = ["SURVEY_DATE", "CONSTRUCTION_NO", "PAVEMENT_FAMILY", *spec["summary"]]
            cols = [c.upper() for c in wanted if repo.has_column(table, c)]
            cols += [f"{c.upper()}_FLAG" for c in spec["summary"] if repo.has_column(table, f"{c}_FLAG")]
        rows, meta, total = read_section_rows(
            repo, table, ref, construction_no=construction_no, date_column="SURVEY_DATE", dates=rng,
            order_by=[("SURVEY_DATE", True)], columns=cols, units=units, drop=DROP, page=None,
        )  # fmt: skip
        if not rows and pavement_type == "auto":
            continue
        legend: dict[str, str] = {}
        for k in [k for k in meta if k.endswith("_flag")]:
            legend.update(meta.pop(k).get("codes", {}))
        if legend:
            meta["flagged"] = {"codes": legend}
        trend = trend_summary(rows, "survey_date", spec["headline"])
        flag_cols = [c for c in (rows[0] if rows else {}) if c.endswith("_flag")]
        for r in rows:
            present = {c[:-5]: r[c] for c in flag_cols if r.get(c) is not None}
            for c in flag_cols:
                r.pop(c, None)
            for k in [k for k, v in r.items() if v is None]:
                del r[k]
            if present:
                r["flagged"] = present
        out[kind] = {
            "dataset": public_title(table),
            "headline_measure": spec["headline"],
            "total_surveys": total,
            "trend": trend,
            "surveys": rows[: page.limit],
        }
        metas.append(meta)
        sources.append(table)
    out_data = {"section": ref.key(), "distress": out, "fields": fields.merge_fields(*metas)}
    notes = [cv.SECTION_KEY, cv.DISTRESS_TABLES, cv.units_note(units)]
    if not out:
        notes.append("This section has no manual distress survey data with these options.")
    if any(s.get("flagged") for v in out.values() for s in v["surveys"]):
        notes.append(cv.FLAGS)
    if "crcp" in out and "OTHER" in repo.omitted_columns().get("ANALYSIS_DIS_CRCP", []):
        notes.append(cv.CRCP_NOTES_OMITTED)
    return respond(out_data, sources=sources, caveats=notes, decoded=True)


def get_load_transfer_history(
    state: str,
    shrp_id: str,
    level: Literal["test_date", "joint"] = "test_date",
    side: Literal["approach", "leave"] | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    exclude_flagged: bool = False,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Load transfer efficiency (LTE, %) of joints in a concrete section from falling-weight deflection tests.

    There are many drops per test, so results are summarised: level="test_date" gives one row per test date
    (drops, mean, min and max LTE, mean drop load), level="joint" one row per test date and joint location
    (POINT_LOC). side: approach or leave slab. exclude_flagged=true drops flagged values. A `summary` gives
    the first, latest and lowest mean LTE. start / end: a year or date. Newest first.
    limit / offset: page through rows (page size capped at 50; use next_offset).
    """
    group = ["TEST_DATE", "PAVEMENT_FAMILY"] + (["POINT_LOC"] if level == "joint" else [])
    extra = [Cond("APPROACH_LEAVE", "eq", "A" if side == "approach" else "L")] if side else []
    ref, rows, meta, summary, total, page = _series(
        state, shrp_id, LTE, group, ["LOAD_TRANSFER_EFFICIENCY", "DROP_LOAD"], ["LTE_FLAG"], "TEST_DATE",
        "load_transfer_efficiency", None, start, end, exclude_flagged, "stored", limit, offset,
        minmax=["LOAD_TRANSFER_EFFICIENCY"], extra=extra, order_desc=True, count_name="drops",
    )  # fmt: skip
    if level == "joint":
        summary = None  # a trend across joints at different stations is not meaningful
    rows = _page_rows(rows, page)
    notes = [cv.SECTION_KEY, cv.LTE_SUMMARISED] + ([cv.FLAGS] if any(r.get("flags") for r in rows) else [])
    return respond(
        {"section": ref.key(), "level": level, "summary": summary, "tests": rows, "fields": meta},
        sources=[LTE, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def get_dowel_scan_results(
    state: str,
    shrp_id: str,
    level: Literal["scan", "joint", "dowel"] = "scan",
    start: int | str | None = None,
    end: int | str | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Magnetic-imaging (MIT) scans of joint dowels in a concrete section.

    level="scan" (default): one row per scan date with joints and dowels scanned, mean and lowest joint
    score, mean dowel score and mean dowel misalignment, skew, tilt and translation. level="joint": one row
    per joint (station, slab thickness, nominal dowel diameter, joint score, dowels, mean dowel score).
    level="dowel": individual dowels (score, misalignment, skew, tilt, position, depth, cover, embedment).
    Higher scores mean better dowel condition. start / end: a year or date.
    limit / offset: page through rows (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    rows, meta, _ = read_section_rows(
        repo, MIT, ref, date_column="MIT_SCAN_DATE", dates=make_range(start, end),
        order_by=[("MIT_SCAN_DATE", True), ("JOINT_NO", False), ("BAR_NO", False)], units=units, drop=DROP,
    )  # fmt: skip

    def mean(vals: list[Any]) -> float | None:
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 3) if v else None

    if level == "dowel":
        shown = rows
    else:
        by_scan: dict[Any, dict[Any, list[dict[str, Any]]]] = {}
        for r in rows:
            by_scan.setdefault(r["mit_scan_date"], {}).setdefault(r["joint_no"], []).append(r)
        shown = []
        for scan_date, joints in by_scan.items():
            joint_rows = []
            for joint_no, dowels in joints.items():
                first = dowels[0]
                joint_rows.append({
                    "mit_scan_date": scan_date, "joint_no": joint_no, "joint_station": first.get("joint_station"),
                    "mit_slab_thickness": first.get("mit_slab_thickness"),
                    "nominal_dowel_diameter": first.get("nominal_dowel_diameter"),
                    "joint_score": first.get("joint_score"), "dowels": len(dowels),
                    "mean_dowel_score": mean([d.get("dowel_score") for d in dowels]),
                    "joint_comment": first.get("joint_comment"),
                })  # fmt: skip
            if level == "joint":
                shown += joint_rows
            else:
                all_dowels = [d for ds in joints.values() for d in ds]
                scores = [j["joint_score"] for j in joint_rows if j["joint_score"] is not None]
                shown.append({
                    "mit_scan_date": scan_date, "joints": len(joint_rows), "dowels": len(all_dowels),
                    "mean_joint_score": mean(scores), "lowest_joint_score": min(scores) if scores else None,
                    "mean_dowel_score": mean([d.get("dowel_score") for d in all_dowels]),
                    "mean_misalignment": mean([d.get("misalignment") for d in all_dowels]),
                    "mean_horizontal_skew": mean([d.get("horizontal_skew") for d in all_dowels]),
                    "mean_vertical_tilt": mean([d.get("vertical_tilt") for d in all_dowels]),
                })  # fmt: skip
    total = len(shown)
    page_rows = [fields.compact(r) for r in _page_rows(shown, page)]
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("This section has no dowel scan (MIT) data.")
    return respond(
        {"section": ref.key(), "level": level, "rows": page_rows, "fields": meta},
        sources=[MIT, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
        page=page,
        total_count=total,
        returned=len(page_rows),
    )


def compare_performance_by_group(
    measure: Measure,
    group_by: PerfGroupBy = "pavement_family",
    pavement_class: PavementClass | None = None,
    pavement_family: str | None = None,
    state: str | None = None,
    region: Region | None = None,
    climate_zone: ClimateZone | None = None,
    experiment: str | None = None,
    gps_sps: GpsSps | None = None,
    top_layer: TopLayer | None = None,
    functional_class: str | None = None,
    age_bin_years: int = 5,
    max_age_years: float | None = None,
    exclude_flagged: bool = True,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """How performance progresses with pavement age for groups of sections, e.g. flexible pavements in
    freeze climates.

    measure: iri (mean roughness index), rutting (max mean rut depth), cracking_ac (fatigue cracking %),
        cracking_jpcc (cracked slabs %), cracking_crcp (punchouts per mile) or lte (load transfer efficiency).
    group_by: pavement_family, pavement_class (flexible / composite / rigid), climate_zone, region, state,
        experiment_type, top_layer, functional_class, gps_sps, or none (one overall curve).
    pavement_class / pavement_family: restrict to flexible (asphalt on a base), composite (asphalt on
        concrete) or rigid (concrete) pavements, or to one family code such as ACUB or JPCTB.
    state, region, climate_zone, experiment, gps_sps, top_layer, functional_class: restrict sections
        (same meaning as search_sections), e.g. climate_zone="wet-freeze" or "dry-freeze".
    age_bin_years: width of the age bins (default 5; 0 = no bins). max_age_years: ignore older records.
    exclude_flagged (default true): drop values LTPP flagged as possible anomalies.
    Each row gives the observations, sections, mean, median, quartiles, min and max for one group and age
    bin. Age is years since the section's recorded construction date. units: stored, us or si.
    """
    repo = get_repository()
    spec = MEASURES[measure]
    f = SectionFilter.create(
        state=state, region=region, climate_zone=climate_zone, experiment=experiment, gps_sps=gps_sps,
        top_layer=top_layer, functional_class=functional_class,
    )  # fmt: skip
    families: list[str] | None = None
    if pavement_class:
        families = list(PAVEMENT_CLASSES[pavement_class])
    if pavement_family:
        fam = pavement_family.strip().upper()
        families = [fam] if families is None else [x for x in families if x == fam]
    page = Page.of(limit, offset)
    rows, total, overall = repo.performance_groups(
        spec, group_by, f, families, max(0, age_bin_years), max_age_years, exclude_flagged, page
    )

    info = repo.field_info(spec.table).get(spec.value.lower())
    stored_unit = info.units if info else None
    conv = conversion_for(stored_unit, units)
    shown_unit = conv.to_unit if conv else stored_unit

    def fix(r: dict[str, Any]) -> dict[str, Any]:
        for k in ("mean", "median", "p25", "p75", "min", "max"):
            r[k] = convert_number(r[k], conv) if conv else r[k]
        if "age_from_years" in r and r["age_from_years"] is not None:
            r["age_years"] = f"{r['age_from_years']}-{r['age_from_years'] + age_bin_years}"
        return r

    return respond(
        {
            "measure": spec.title,
            "value_column": spec.value.lower(),
            "units": shown_unit,
            "group_by": group_by,
            "age_bin_years": age_bin_years if age_bin_years > 0 else None,
            "overall": fix(dict(overall)),
            "rows": [fix(r) for r in rows],
        },
        sources=[spec.table, "LDW_DP_GENERAL"],
        caveats=[
            cv.SECTION_KEY,
            cv.AGE_BASIS,
            cv.units_note(units),
            *([cv.FLAGS] if exclude_flagged and spec.flags else []),
            *([cv.IRI_RUNS] if measure == "iri" else []),
        ],  # fmt: skip
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def register(mcp: FastMCP) -> None:
    for tool in (
        get_roughness_history,
        get_rutting_history,
        get_cracking_history,
        get_load_transfer_history,
        get_dowel_scan_results,
        compare_performance_by_group,
    ):
        mcp.tool()(tool)


_ = Select  # imported for callers that build queries from this module
