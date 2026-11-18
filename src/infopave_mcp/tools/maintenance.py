"""Maintenance and rehabilitation (ARMRD): treatment history and details, and performance around treatments."""

from typing import Any

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Cond, Envelope, Page, SectionGroup, make_group, make_range
from infopave_mcp.models.inputs import Measure, TreatmentGroupBy, Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields, treatments
from infopave_mcp.services.measures import MEASURES
from infopave_mcp.services.readers import read_section_rows
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section

SUMMARY = "ANALYSIS_MNT_RHB_SUMMARY"
DROP = ("state_code", "shrp_id", "record_status", "data_rec_id")
Treatment = int | str | list[int | str] | None

_DIRECTION = {"iri": "lower", "rutting": "lower", "cracking_ac": "lower", "cracking_jpcc": "lower",
              "cracking_crcp": "lower", "lte": "higher"}  # fmt: skip


def _treatment_conds(repo: Any, treatment: Treatment) -> list[Cond]:
    codes = treatments.resolve_treatments(repo, treatment)
    return [Cond("MAINT_WORK", "in", codes)] if codes else []


def get_treatment_history(
    state: str,
    shrp_id: str,
    treatment: Treatment = None,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Maintenance and rehabilitation treatments of a section, with dates, oldest first.

    treatment: a treatment code (19) or a word from its name ("overlay", "crack seal", "patch"), or a list.
    construction_no: the construction event the treatment belongs to. start / end: a year or date.
    Each row gives the treatment (code and name) and whether it is a `surface` treatment (overlay, milling,
    reconstruction: changes the structure) or `spot / maintenance`, the date, the pavement family before
    the treatment, whether quantities/materials are known, and the PRIOR/POST intervals (months) to the
    nearest profile, distress and deflection measurements on the same structure (empty where no valid
    comparison exists). `comparisons_possible` lists the data types a before/after analysis can use.
    limit / offset: page through treatments (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    rows, meta, total = read_section_rows(
        repo, SUMMARY, ref, construction_no=construction_no, extra=_treatment_conds(repo, treatment),
        date_column="IMP_DATE", dates=make_range(start, end),
        order_by=[("IMP_DATE", False), ("MAINT_WORK", False)], page=page, drop=DROP,
    )  # fmt: skip
    treatments.add_treatment_names(repo, rows)
    for r in rows:
        surface = r["treatment_type"] == "surface"
        possible = []
        for kind in ("profile", "distress", "deflection"):
            before, after = r.get(f"prior_{kind}_interval"), r.get(f"post_{kind}_interval")
            if before is not None and (after is not None or surface):
                possible.append(kind)
        r["comparisons_possible"] = possible
    return respond(
        {"section": ref.key(), "treatments": rows, "fields": meta},
        sources=[SUMMARY, "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.INTERVAL_RULE],
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def _details(
    kind: str, tables: dict[str, str], state: str, shrp_id: str, treatment: Treatment,
    construction_no: int | None, start: int | str | None, end: int | str | None, units: str,
) -> Envelope:  # fmt: skip
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = _treatment_conds(repo, treatment)
    rng = make_range(start, end)
    data: dict[str, Any] = {"section": ref.key()}
    metas: list[dict[str, dict[str, Any]]] = []
    sources = ["LDW_DP_GENERAL"]
    any_rows = False
    for label, table in tables.items():
        rows, meta, _ = read_section_rows(
            repo, table, ref, construction_no=construction_no, extra=extra, date_column="DATE_COMPLETE",
            dates=rng, order_by=[("DATE_COMPLETE", False), ("MAINT_WORK", False)], units=units, drop=DROP,
            page=Page.of(50, 0),
        )  # fmt: skip
        treatments.add_treatment_names(repo, rows)
        data[label] = [fields.compact(r) for r in rows]
        any_rows = any_rows or bool(rows)
        metas.append(meta)
        sources.append(table)
    data["fields"] = fields.merge_fields(*metas)
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not any_rows:
        notes.append(f"No {kind} treatment details are recorded for this section with these options.")
    return respond(data, sources=sources, caveats=notes, decoded=True)


def get_ac_treatment_details(
    state: str,
    shrp_id: str,
    treatment: Treatment = None,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    units: Units = "stored",
) -> Envelope:
    """Materials and quantities of asphalt (AC) pavement maintenance and rehabilitation at a section.

    `spot` lists crack sealing (length, material, severity), surface and full-depth patches (number, area,
    material). `surface` lists seal coats, overlays and milling: thickness, asphalt grade, gradation,
    specific gravity, air voids, aggregate types, pavement type, milling method and depth. Up to 50
    records per list, oldest first. treatment: code or word ("overlay"). start / end: a year or date.
    """
    return _details("asphalt", {"spot": "ANALYSIS_MNT_RHB_AC_SPOT", "surface": "ANALYSIS_MNT_RHB_AC_SURFACE"},
                    state, shrp_id, treatment, construction_no, start, end, units)  # fmt: skip


def get_pcc_treatment_details(
    state: str,
    shrp_id: str,
    treatment: Treatment = None,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    units: Units = "stored",
) -> Envelope:
    """Materials and quantities of Portland cement concrete (PCC) pavement maintenance and rehabilitation.

    `spot` lists crack and joint sealing (lengths, sealant, reservoir size), patches (number, area, depth,
    material) and slab replacement. `surface` lists grinding or overlay work (method, extent, depth, milling
    thickness). Up to 50 records per list, oldest first. treatment: code or word. start / end: year or date.
    """
    return _details("concrete", {"spot": "ANALYSIS_MNT_RHB_PCC_SPOT", "surface": "ANALYSIS_MNT_RHB_PCC_SURFACE"},
                    state, shrp_id, treatment, construction_no, start, end, units)  # fmt: skip


def get_subdrainage_treatment_details(
    state: str,
    shrp_id: str,
    treatment: Treatment = None,
    construction_no: int | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    units: Units = "stored",
) -> Envelope:
    """Subdrainage maintenance and rehabilitation at a section: pipe type, diameter and depth, outlet
    interval, filter type, maximum particle size and permeability. Up to 50 records, oldest first."""
    return _details("subdrainage", {"subdrainage": "ANALYSIS_MNT_RHB_SUBDRAINAGE"},
                    state, shrp_id, treatment, construction_no, start, end, units)  # fmt: skip


def get_performance_around_treatment(
    state: str,
    shrp_id: str,
    treatment: Treatment = None,
    measures: list[Measure] | None = None,
    start: int | str | None = None,
    end: int | str | None = None,
    exclude_flagged: bool = True,
    include_unavailable: bool = False,
    units: Units = "stored",
) -> Envelope:
    """Performance of a section just before and after each treatment.

    measures: any of iri (roughness MRI), rutting (max rut depth), cracking_ac, cracking_jpcc,
        cracking_crcp, lte (load transfer efficiency). Default: all that apply.
    treatment: a code (19) or word ("overlay", "crack seal") or a list; start / end: a year or date.
    For each treatment and measure with a valid pair: the value and date before and after, the months
    between each and the treatment, and the change. exclude_flagged (default true) ignores values LTPP
    flagged as possible anomalies. include_unavailable=true also lists why a measure had no valid pair.
    How pairs are chosen: the 'before' value is the last measurement on or before the treatment date and
    needs a valid prior interval in the treatment record. The 'after' value is the first measurement after
    the treatment: for spot treatments the record must give a valid post interval; for surface treatments
    (overlays, milling, reconstruction) LTPP gives none by design, so the first measurement on the new
    structure is used. The result is observational, not proof the treatment caused the change.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    chosen: list[str] = list(measures) if measures else list(MEASURES)
    bad = [m for m in chosen if m not in MEASURES]
    if bad:
        raise ValueError(f"Unknown measure(s) {bad}. Choose from: {', '.join(MEASURES)}.")
    codes = treatments.resolve_treatments(repo, treatment)
    surface = treatments.surface_codes(repo)
    rng = make_range(start, end)

    by_treatment: dict[tuple[Any, ...], dict[str, Any]] = {}
    unavailable: dict[str, dict[str, int]] = {}
    sources = [SUMMARY, "LDW_DP_GENERAL"]
    units_shown: dict[str, str | None] = {}
    for key in chosen:
        spec = MEASURES[key]
        rows = repo.treatment_pairs(
            spec, state_code=ref.state_code, shrp_id=ref.shrp_id, maint_codes=codes,
            surface_codes=surface, exclude_flagged=exclude_flagged, dates=rng,
        )  # fmt: skip
        if not rows:
            continue
        sources.append(spec.table)
        info = repo.field_info(spec.table).get(spec.value.lower())
        valid = [r for r in rows if r["status"] == "valid"]
        units_shown[key] = treatments.convert_pair_values(info.units if info else None, units, valid)
        for r in rows:
            slot = by_treatment.setdefault(
                (r["imp_date"], r["maint_work"], r["construction_no"]),
                {
                    "maint_work": r["maint_work"], "imp_date": r["imp_date"],
                    "construction_no": r["construction_no"], "measures": {},
                },
            )  # fmt: skip
            if r["status"] == "valid":
                change = round(r["after_value"] - r["before_value"], 4)
                before = r["before_value"]
                slot["measures"][key] = {
                    "before": {"date": r["before_date"], "value": before, "months_before_treatment": r["months_before"]},
                    "after": {"date": r["after_date"], "value": r["after_value"], "months_after_treatment": r["months_after"]},
                    "change": change,
                    "change_percent": round(100 * change / before, 1) if before else None,
                    "pairing": "first measurement on the new structure" if r["surface"] else "valid after-interval in the record",
                }  # fmt: skip
            else:
                unavailable.setdefault(key, {})
                unavailable[key][r["status"]] = unavailable[key].get(r["status"], 0) + 1
                if include_unavailable:
                    slot.setdefault("unavailable", {})[key] = r["status"]

    out = sorted(by_treatment.values(), key=lambda t: (str(t["imp_date"]), str(t["maint_work"])))
    treatments.add_treatment_names(repo, out)
    shown = [t for t in out if t["measures"] or include_unavailable]
    notes = [cv.SECTION_KEY, cv.INTERVAL_RULE, cv.OBSERVATIONAL, cv.units_note(units)]
    if exclude_flagged:
        notes.append(cv.FLAGS)
    if not shown:
        notes.append("No treatment has a valid before and after measurement with these options.")
    return respond(
        {
            "section": ref.key(),
            "units": units_shown,
            "treatments": shown,
            "pairs_not_available": unavailable,
        },
        sources=sources,
        caveats=notes,
        decoded=True,
    )


def compare_treatment_effect_across_groups(
    measure: Measure,
    treatment: Treatment,
    group_a: SectionGroup | None = None,
    group_b: SectionGroup | None = None,
    group_by: TreatmentGroupBy | None = None,
    exclude_flagged: bool = True,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """How much a performance measure changes after a treatment, compared between groups of sections, e.g.
    roughness change after an overlay for thick asphalt in wet-freeze climates versus thin asphalt.

    measure: iri, rutting, cracking_ac, cracking_jpcc, cracking_crcp or lte.
    treatment: a code (19) or word ("overlay", "seal coat", "crack seal") or a list; a word matches every
        treatment whose name contains it (listed in `treatments_included`).
    Two ways to define groups:
    1. group_a and group_b: each an object with optional label, state/states, region, climate_zone
       (wet-freeze, wet-no-freeze, dry-freeze, dry-no-freeze), experiment, gps_sps, top_layer,
       functional_class, county, constructed_after/before, pavement_class (flexible, composite, rigid:
       the pavement family BEFORE the treatment), and min_ac_thickness_in / max_ac_thickness_in (asphalt
       thickness of the structure the before-measurement belongs to).
    2. group_by (instead of, or with group_a as a base filter): split by climate_zone, region, state,
       experiment_type, top_layer, functional_class, gps_sps, pavement_family or treatment.
    For each group: the treatments with a valid before and after, the sections, mean before and after,
    mean and median change, SD, quartiles, how many measurements fell and rose, and the average months
    between measurement and treatment. For two groups the difference in mean change comes with a Welch
    t-statistic and an approximate 95% interval. Pairing rules and caveats are in `caveats`: results are
    observational, small groups are noisy, and exclude_flagged (default true) drops flagged values.
    """
    repo = get_repository()
    if measure not in MEASURES:
        raise ValueError(f"Unknown measure '{measure}'. Choose from: {', '.join(MEASURES)}.")
    spec = MEASURES[measure]
    page = Page.of(limit, offset)
    codes = treatments.resolve_treatments(repo, treatment)
    if codes is None:
        raise ValueError('Say which treatment to analyse, e.g. treatment="overlay" or treatment=19.')
    surface = treatments.surface_codes(repo)
    info = repo.field_info(spec.table).get(spec.value.lower())
    stored_unit = info.units if info else None
    from infopave_mcp.services.units import conversion_for, convert_number

    conv = conversion_for(stored_unit, units)
    scale = (conv.convert(1.0) - conv.convert(0.0)) if conv else 1.0

    def run(group: SectionGroup, by: str | None) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows, n, status = repo.treatment_effect(
            spec, group, maint_codes=codes, surface_codes=surface, exclude_flagged=exclude_flagged,
            group_by=by, page=page,
        )  # fmt: skip
        for r in rows:
            for k in ("mean_before", "mean_after"):
                r[k] = convert_number(r[k], conv) if conv else r[k]
            for k in ("mean_change", "median_change", "std_dev_change", "p25_change", "p75_change"):
                if r.get(k) is not None:
                    r[k] = round(r[k] * scale, 4)
            n_t = r["treatments"]
            r["share_decreased"] = round(r["decreased"] / n_t, 3) if n_t else None
            r["share_increased"] = round(r["increased"] / n_t, 3) if n_t else None
        return rows, n, status

    data: dict[str, Any] = {
        "measure": spec.title,
        "units": conv.to_unit if conv else stored_unit,
        "better_when": f"{_DIRECTION[measure]} values are better",
        "treatments_included": treatments.describe_treatments(repo, codes),
    }
    sources = [spec.table, SUMMARY, "LDW_DP_GENERAL"]
    notes = [cv.SECTION_KEY, cv.INTERVAL_RULE, cv.OBSERVATIONAL, cv.TREATMENT_COUNTS, cv.units_note(units)]
    if group_a is not None and group_b is not None and group_by is None:
        a, b = make_group(group_a, "Group A"), make_group(group_b, "Group B")
        results = {}
        statuses = {}
        for label, grp in ((a.title("Group A"), a), (b.title("Group B"), b)):
            rows, _, status = run(grp, None)
            row = {k: v for k, v in (rows[0] if rows else {}).items() if k != "group"}
            results[label] = row or {"treatments": 0, "sections": 0}
            statuses[label] = status
        data["groups"] = results
        data["pairs_not_available"] = statuses
        (la, ra), (lb, rb) = list(results.items())
        if ra["treatments"] and rb["treatments"]:
            diff = round(ra["mean_change"] - rb["mean_change"], 4)
            entry: dict[str, Any] = {"difference_in_mean_change_a_minus_b": diff}
            sa, sb = ra.get("std_dev_change"), rb.get("std_dev_change")
            if sa is not None and sb is not None and ra["treatments"] > 1 and rb["treatments"] > 1:
                se = (sa**2 / ra["treatments"] + sb**2 / rb["treatments"]) ** 0.5
                if se > 0:
                    entry["welch_t"] = round(diff / se, 2)
                    entry["approx_95pct_interval"] = [round(diff - 1.96 * se, 4), round(diff + 1.96 * se, 4)]
            data["comparison"] = entry
            notes += cv.small_sample(min(ra["treatments"], rb["treatments"]))
        else:
            notes.append("At least one group has no treatment with a valid before and after measurement.")
        if any(g.min_ac_thickness_in is not None or g.max_ac_thickness_in is not None for g in (a, b)):
            notes.append("AC thickness is that of the pavement structure the before-measurement belongs to.")
        total = 2
    elif group_by is not None or group_a is not None:
        base = make_group(group_a, "Base filter")
        rows, total, status = run(base, group_by)
        data["group_by"] = group_by or "none"
        data["groups"] = rows
        data["pairs_not_available"] = status
        if rows:
            notes += cv.small_sample(min(r["treatments"] for r in rows))
    else:
        raise ValueError("Give group_a and group_b, or group_by (optionally with group_a as a base filter).")
    return respond(
        data,
        sources=sources,
        caveats=notes,
        decoded=True,
        page=page,
        total_count=total if group_by else None,
        returned=len(data["groups"]) if group_by else None,
    )


def register(mcp: FastMCP) -> None:
    for tool in (
        get_treatment_history,
        get_ac_treatment_details,
        get_pcc_treatment_details,
        get_subdrainage_treatment_details,
        get_performance_around_treatment,
        compare_treatment_effect_across_groups,
    ):
        mcp.tool()(tool)
