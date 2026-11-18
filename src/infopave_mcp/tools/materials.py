"""Materials (ARMAD): layer structure, layer properties, dynamic modulus, creep compliance, variability and
group statistics."""

from typing import Any

from fastmcp import FastMCP

from infopave_mcp.config import DEFAULT_PAGE
from infopave_mcp.models import Cond, Envelope, Page, SectionFilter
from infopave_mcp.models.inputs import LayerMaterial, MaterialGroupBy, SupportMaterial, Units
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services import fields
from infopave_mcp.services.materials import (
    ASPHALT_KINDS,
    IDENTITY,
    KINDS,
    LAYER_KINDS,
    read_layers,
)
from infopave_mcp.services.readers import read_section_rows
from infopave_mcp.services.response import respond
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.services.units import conversion_for, convert_number

ESTAR = "ANALYSIS_TST_AC_ESTAR"


def _layer_properties(
    kinds: tuple[str, ...],
    state: str,
    shrp_id: str,
    construction_no: int | None,
    layer_no: int | None,
    units: str,
    include_variability: bool = False,
) -> Envelope:
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    layers, meta, tables, _ = read_layers(
        repo, kinds, ref, construction_no=construction_no, layer_no=layer_no, units=units,
        with_variability=include_variability,
    )  # fmt: skip
    if include_variability:
        meta = fields.merge_fields(meta, {"source_quality": {"codes": _quality_legend(layers, repo)}} if layers else {})
    notes = [cv.SECTION_KEY, cv.MATERIAL_REPRESENTATIVE, cv.units_note(units)]
    if not layers:
        notes.append("No layers of this material type are recorded for the section with these options.")
    return respond(
        {"section": ref.key(), "layers": layers, "fields": meta},
        sources=[*tables, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def _quality_legend(layers: list[dict[str, Any]], repo: Any) -> dict[str, str]:
    labels = repo.code_labels("REP_CODE_SOURCE_VARIABILITY")
    used = {q.get("source_quality") for layer in layers for q in layer.get("property_quality", {}).values()}
    return {c: labels[c] for c in sorted(x for x in used if x) if c in labels}


def get_layer_structure(
    state: str, shrp_id: str, construction_no: int | None = None, units: Units = "stored"
) -> Envelope:
    """Layer order, type and thickness of a test section, for each construction event.

    state: name, postal abbreviation or numeric code. shrp_id: the section's SHRP_ID (e.g. "0207").
    construction_no: one construction event (1 = as accepted into LTPP; each structural change adds one);
    omit for all events. Layers are listed surface first; layer 1 is the subgrade. Each event also gives
    total thickness and the asphalt and concrete thicknesses. units: stored (inches), us or si.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    layers, meta, tables, _ = read_layers(
        repo, LAYER_KINDS, ref, construction_no=construction_no, units=units, identity_only=True
    )
    events: dict[Any, dict[str, Any]] = {}
    for layer in layers:
        ev = events.setdefault(
            layer.get("construction_no"), {"construction_no": layer.get("construction_no"), "layers": []}
        )
        ev["layers"].append(layer)
    for ev in events.values():
        thick = [(layer.get("layer_type"), layer.get("repr_thickness")) for layer in ev["layers"]]
        ev["total_thickness"] = round(sum(t for _, t in thick if t is not None), 3)
        ev["asphalt_thickness"] = round(sum(t for lt, t in thick if lt == "AC" and t is not None), 3)
        ev["concrete_thickness"] = round(sum(t for lt, t in thick if lt == "PC" and t is not None), 3)
        ev["layer_count"] = len(ev["layers"])
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not events:
        notes.append("No layer records for this section with these options.")
    return respond(
        {"section": ref.key(), "construction_events": list(events.values()), "fields": meta},
        sources=[*tables, "LDW_DP_GENERAL"],
        caveats=notes,
        decoded=True,
    )


def get_asphalt_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Properties of asphalt concrete (AC) and AC-treated layers of a section.

    Per layer: binder (DSR modulus and phase angle, viscosity), aggregate gradation (percent passing),
    volumetrics (air voids, asphalt content, specific gravity, VMA/VFA), strength tests (IDT) and thermal
    properties. Only non-empty values are shown. Optional construction_no / layer_no narrow the layers.
    include_variability=true adds, for each value, its sample count, coefficient of variation and source
    quality; get_property_variability gives the full statistics.
    """
    return _layer_properties(ASPHALT_KINDS, state, shrp_id, construction_no, layer_no, units, include_variability)


def get_concrete_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Properties of Portland cement concrete (PCC) layers of a section.

    Per layer: strength and modulus (compressive, tensile, modulus of rupture, elastic modulus, Poisson's
    ratio), mix (unit weight, water-cement ratio), thermal expansion and shrinkage, and reinforcement
    details (bar spacing, diameter, depth). Only non-empty values are shown.
    """
    return _layer_properties(("pcc",), state, shrp_id, construction_no, layer_no, units, include_variability)


def get_pcc_treated_layer_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Material properties of PCC-treated (cement-treated) layers of a section: treatment material and type,
    aggregate type, strength, elastic and resilient modulus, unit weight, thermal properties."""
    return _layer_properties(("pcc_treated",), state, shrp_id, construction_no, layer_no, units, include_variability)


def get_unbound_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Properties of unbound layers (granular base, subbase, subgrade) of a section.

    Per layer: gradation (percent passing), Atterberg limits and soil classification, density and moisture,
    resilient modulus (and its k1/k2/k3 coefficients), Poisson's ratio and hydraulic conductivity.
    """
    return _layer_properties(("unbound",), state, shrp_id, construction_no, layer_no, units, include_variability)


def get_interlayer_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Properties of interlayers and treatment layers of a section (thin layers between pavement layers)."""
    return _layer_properties(("interlayer",), state, shrp_id, construction_no, layer_no, units, include_variability)


def get_engineering_fabric_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
    include_variability: bool = False,
) -> Envelope:
    """Properties of engineering fabric (geotextile / geogrid) layers of a section: layer position and thickness, material
    and the test properties recorded for the fabric. Only non-empty values are shown. Few sections have a fabric
    layer, so an empty result is normal. include_variability=true adds sample count, CV and source quality."""
    return _layer_properties(("fabric",), state, shrp_id, construction_no, layer_no, units, include_variability)


def get_wma_properties(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: Units = "stored",
) -> Envelope:
    """Warm-mix asphalt (WMA) binder and mix test results for a section.

    Binder: DSR complex modulus (high and intermediate grade), BBR stiffness and m-value, MSCR recovery
    and non-recoverable compliance. Mix: Hamburg wheel-tracking failure, Fenix fracture energy, dynamic
    modulus. Each value comes with its statistics (min, max, median, mean, SD, CV, sample count and the
    quality of its source). Few sections have WMA data; an empty result is normal.
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = [Cond("LAYER_NO", "eq", layer_no)] if layer_no is not None else []
    out: dict[str, Any] = {"section": ref.key()}
    metas: list[dict[str, dict[str, Any]]] = []
    sources: list[str] = ["LDW_DP_GENERAL"]
    for key in ("wma_binder", "wma_mix"):
        kind = KINDS[key]
        assert kind.support
        rows, meta, _ = read_section_rows(
            repo, kind.table, ref, construction_no=construction_no, extra=extra,
            order_by=[("LAYER_NO", False)], units=units,
        )  # fmt: skip
        stats, smeta, _ = read_section_rows(
            repo, kind.support, ref, construction_no=construction_no, extra=extra,
            order_by=[("LAYER_NO", False), ("MATL_PROPERTY", False)], units="stored",
            drop=("state_code", "shrp_id", "conversion_id", "data_rec_support_id", "record_status"),
        )  # fmt: skip
        stats = _convert_stats(repo, kind.table, stats, units)
        out[key] = [fields.compact(r) for r in rows]
        out[f"{key}_statistics"] = [fields.compact(r) for r in stats]
        metas += [meta, smeta]
        sources += [kind.table, kind.support]
    out["fields"] = fields.merge_fields(*metas)
    notes = [cv.SECTION_KEY, cv.MATERIAL_REPRESENTATIVE, cv.units_note(units)]
    if not out["wma_binder"] and not out["wma_mix"]:
        notes.append("This section has no warm-mix asphalt test data.")
    return respond(out, sources=sources, caveats=notes, decoded=True)


def get_dynamic_modulus(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    lab_measured: bool | None = None,
    temperature_c: float | None = None,
    frequency_hz: float | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Dynamic modulus of asphalt layers by temperature and frequency (master-curve points).

    Each row is one temperature/frequency point for an asphalt layer, labelled with where it came from:
    source = "lab-measured" (tested on field specimens, with specimen type) or "predicted" (from a
    predictive model, whose code is given). lab_measured=True/False keeps only one kind. temperature_c and
    frequency_hz pick one test condition. Modulus is in kPa as stored; phase angle in degrees.
    limit / offset: page through rows (page size capped at 50; use next_offset).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    extra: list[Cond] = []
    if layer_no is not None:
        extra.append(Cond("LAYER_NO", "eq", layer_no))
    if lab_measured is not None:
        extra.append(Cond("LAB_MEASURED", "eq", "Y" if lab_measured else "N"))
    if temperature_c is not None:
        extra.append(Cond("TEMPERATURE", "eq", temperature_c))
    if frequency_hz is not None:
        extra.append(Cond("FREQUENCY", "eq", frequency_hz))
    rows, meta, total = read_section_rows(
        repo, ESTAR, ref, construction_no=construction_no, extra=extra,
        order_by=[("CONSTRUCTION_NO", False), ("LAYER_NO", False), ("LAB_MEASURED", True), ("TEMPERATURE", False), ("FREQUENCY", False)],
        page=page, units=units, drop=("state_code", "shrp_id", "record_status"),
    )  # fmt: skip
    for r in rows:
        r["source"] = "lab-measured" if r.get("lab_measured") == "Y" else "predicted"
        for k in [k for k, v in r.items() if v is None]:
            del r[k]
    return respond(
        {"section": ref.key(), "rows": rows, "fields": meta},
        sources=[ESTAR, "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.units_note(units)],
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def get_creep_compliance(
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    include_statistics: bool = True,
    units: Units = "stored",
) -> Envelope:
    """Creep compliance of asphalt layers at 1, 2, 5, 10, 20, 50 and 100 seconds, by test temperature.

    include_statistics (default true) adds, for each layer and temperature, the statistics behind each value
    (min, max, median, mean, SD, CV, sample count and source quality).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    extra = [Cond("LAYER_NO", "eq", layer_no)] if layer_no is not None else []
    kind = KINDS["creep"]
    rows, meta, _ = read_section_rows(
        repo, kind.table, ref, construction_no=construction_no, extra=extra,
        order_by=[("CONSTRUCTION_NO", False), ("LAYER_NO", False), ("TEST_TEMPERATURE", False)],
        units=units, drop=("state_code", "shrp_id", "record_status", "data_rec_id"),
    )  # fmt: skip
    data: dict[str, Any] = {"section": ref.key(), "creep_compliance": rows}
    metas = [meta]
    sources = [kind.table, "LDW_DP_GENERAL"]
    if include_statistics and kind.support:
        stats, smeta, _ = read_section_rows(
            repo, kind.support, ref, construction_no=construction_no, extra=extra,
            order_by=[("CONSTRUCTION_NO", False), ("LAYER_NO", False), ("TEST_TEMPERATURE", False), ("MATL_PROPERTY", False)],
            units="stored", drop=("state_code", "shrp_id", "conversion_id", "data_rec_support_id", "record_status"),
        )  # fmt: skip
        data["statistics"] = [fields.compact(r) for r in _convert_stats(repo, kind.table, stats, units)]
        metas.append(smeta)
        sources.append(kind.support)
    data["fields"] = fields.merge_fields(*metas)
    notes = [cv.SECTION_KEY, cv.units_note(units)]
    if not rows:
        notes.append("This section has no creep compliance results.")
    return respond(data, sources=sources, caveats=notes, decoded=True)


def get_property_variability(
    material: SupportMaterial,
    state: str,
    shrp_id: str,
    construction_no: int | None = None,
    layer_no: int | None = None,
    property: str | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Spread and source quality of material properties: min, max, median, mean, SD, CV, sample count.

    material: asphalt, asphalt_treated, pcc, pcc_treated, unbound, interlayer, fabric, creep, wma_binder or
        wma_mix. property: part of a property name (e.g. "AIR_VOIDS", "COMP_STRENGTH", "PASSING").
    `source_quality` (REP_CODE_SOURCE_VARIABILITY) is LTPP's rating of how a representative value was
    obtained: measured, calculated or imputed, from a single measurement or several, and for several
    whether the coefficient of variation was low (L) or high (H) against a material-specific threshold.
    Units are those of the property itself. limit / offset: page through rows (page size capped at 50).
    """
    repo = get_repository()
    ref = resolve_section(repo, state, shrp_id)
    page = Page.of(limit, offset)
    kind = KINDS[material]
    assert kind.support
    extra: list[Cond] = []
    if layer_no is not None:
        extra.append(Cond("LAYER_NO", "eq", layer_no))
    if property:
        extra.append(Cond("MATL_PROPERTY", "like", property.strip().upper()))
    order = (
        [("CONSTRUCTION_NO", False), ("LAYER_NO", False)]
        if repo.has_column(kind.support, "CONSTRUCTION_NO")
        else [("LAYER_NO", False)]
    )
    order.append(("MATL_PROPERTY", False))
    rows, meta, total = read_section_rows(
        repo, kind.support, ref, construction_no=construction_no, extra=extra, order_by=order, page=page,
        units="stored", drop=("state_code", "shrp_id", "conversion_id", "data_rec_support_id", "record_status"),
    )  # fmt: skip
    rows = _convert_stats(repo, kind.table, rows, units)
    for r in rows:
        r["source_quality"] = r.pop("rep_code_source_variability", None)
    meta = {("source_quality" if k == "rep_code_source_variability" else k): v for k, v in meta.items()}
    return respond(
        {
            "section": ref.key(),
            "material": kind.title,
            "rows": [fields.compact(r, keep=("sample_count",)) for r in rows],
            "fields": meta,
        },
        sources=[kind.support, kind.table, "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.MATERIAL_REPRESENTATIVE, cv.units_note(units)],
        decoded=True,
        page=page,
        total_count=total,
        returned=len(rows),
    )


def summarize_material_by_group(
    material: LayerMaterial,
    property: str = "repr_thickness",
    group_by: MaterialGroupBy = "state",
    layer_type: str | None = None,
    state: str | None = None,
    region: str | None = None,
    climate_zone: str | None = None,
    experiment: str | None = None,
    gps_sps: str | None = None,
    top_layer: str | None = None,
    functional_class: str | None = None,
    units: Units = "stored",
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> Envelope:
    """Group statistics of one layer property, e.g. asphalt layer thickness for sections in a state.

    material: asphalt, asphalt_treated, pcc, pcc_treated, unbound, interlayer or fabric.
    property: a numeric column of that material's table (default repr_thickness, the layer thickness; also
        e.g. air_voids_avg_wp, asphalt_content_mean, comp_strength, resilient_modulus, no_200_passing).
    group_by: state, region, climate_zone, experiment_type, sps_project, gps_sps, top_layer,
        functional_class, construction_decade or layer_type.
    layer_type: keep one layer type (AC, PC, GB base, GS subbase, SS subgrade, TB, TS, EF).
    state, region, climate_zone, experiment, gps_sps, top_layer, functional_class: restrict which sections
        are included (same meaning as search_sections).
    Each group gives layers, sections, mean, median, SD, min, max and quartiles of the property.
    """
    repo = get_repository()
    kind = KINDS[material]
    col = property.strip().lower()
    numeric = [c for c in repo.numeric_columns(kind.table) if c not in IDENTITY - {"repr_thickness"}]
    if col not in numeric:
        raise ValueError(
            f"'{property}' is not a numeric property of {material} layers. Choose from: {', '.join(numeric)}."
        )
    f = SectionFilter.create(
        state=state, region=region, climate_zone=climate_zone, experiment=experiment, gps_sps=gps_sps,
        top_layer=top_layer, functional_class=functional_class,
    )  # fmt: skip
    page = Page.of(limit, offset)
    layer_types = [layer_type.strip().upper()] if layer_type else None
    rows, n_groups, overall = repo.material_group_stats(kind.table, col, group_by, f, layer_types, page)

    unit = repo.field_info(kind.table).get(col)
    stored_unit = unit.units if unit else None
    conv = conversion_for(stored_unit, units)
    shown_unit = conv.to_unit if conv else stored_unit
    scale = (conv.convert(1.0) - conv.convert(0.0)) if conv else 1.0

    def fix(r: dict[str, Any]) -> dict[str, Any]:
        for k in ("mean", "median", "min", "max", "p25", "p75"):
            r[k] = convert_number(r[k], conv) if conv else _round(r[k])
        r["std_dev"] = _round(r["std_dev"] * scale) if r.get("std_dev") is not None else None
        return r

    groups = [fix(r) for r in rows]
    overall = fix(dict(overall))
    return respond(
        {
            "material": kind.title,
            "property": col,
            "units": shown_unit,
            "group_by": group_by,
            "overall": overall,
            "groups": groups,
        },
        sources=[kind.table, "LDW_DP_GENERAL"],
        caveats=[cv.SECTION_KEY, cv.MATERIAL_REPRESENTATIVE, cv.units_note(units)],
        decoded=True,
        page=page,
        total_count=n_groups,
        returned=len(groups),
    )


def _round(v: Any) -> Any:
    return round(v, 4) if isinstance(v, float) else v


def _convert_stats(repo: Any, main_table: str, rows: list[dict[str, Any]], units: str) -> list[dict[str, Any]]:
    """Convert min/max/median/mean (and SD by scale only) of a support table to the requested units,
    using the unit of each property in its main table. Adds `units` to every row."""
    info = repo.field_info(main_table)
    for r in rows:
        prop = str(r.get("matl_property", "")).lower()
        unit = info[prop].units if prop in info else None
        conv = conversion_for(unit, units)
        if conv is not None:
            scale = conv.convert(1.0) - conv.convert(0.0)
            for k in ("property_minimum", "property_maximum", "property_median", "property_average"):
                r[k] = convert_number(r.get(k), conv)
            if r.get("property_standard_deviation") is not None:
                r["property_standard_deviation"] = round(r["property_standard_deviation"] * scale, 4)
            r["units"] = conv.to_unit
        elif unit:
            r["units"] = unit
    return rows


def register(mcp: FastMCP) -> None:
    for tool in (
        get_layer_structure,
        get_asphalt_properties,
        get_wma_properties,
        get_concrete_properties,
        get_pcc_treated_layer_properties,
        get_unbound_properties,
        get_interlayer_properties,
        get_engineering_fabric_properties,
        get_dynamic_modulus,
        get_creep_compliance,
        get_property_variability,
        summarize_material_by_group,
    ):
        mcp.tool()(tool)
