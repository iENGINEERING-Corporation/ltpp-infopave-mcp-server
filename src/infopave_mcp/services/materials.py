"""Materials (ARMAD): which table holds what, and how to present a layer's properties."""

from dataclasses import dataclass
from typing import Any

from infopave_mcp.models import Cond, Page
from infopave_mcp.repository.base import Repository, Row
from infopave_mcp.services import fields
from infopave_mcp.services.readers import read_section_rows
from infopave_mcp.services.sections import SectionRef


@dataclass(frozen=True)
class MaterialKind:
    key: str
    title: str
    table: str
    support: str | None


KINDS: dict[str, MaterialKind] = {
    k.key: k
    for k in [
        MaterialKind("asphalt", "Asphalt concrete (AC) layer", "ANALYSIS_TST_AC", "ANALYSIS_TST_AC_SUPPORT"),
        MaterialKind("asphalt_treated", "AC-treated layer", "ANALYSIS_TST_ACT", "ANALYSIS_TST_ACT_SUPPORT"),
        MaterialKind("pcc", "Portland cement concrete (PCC) layer", "ANALYSIS_TST_PCC", "ANALYSIS_TST_PCC_SUPPORT"),
        MaterialKind("pcc_treated", "PCC-treated layer", "ANALYSIS_TST_PCT", "ANALYSIS_TST_PCT_SUPPORT"),
        MaterialKind("unbound", "Unbound layer", "ANALYSIS_TST_UNBOUND", "ANALYSIS_TST_UNBOUND_SUPPORT"),
        MaterialKind("interlayer", "Interlayer / treatment layer", "ANALYSIS_TST_TR", "ANALYSIS_TST_TR_SUPPORT"),
        MaterialKind("fabric", "Engineering fabric layer", "ANALYSIS_TST_EF", "ANALYSIS_TST_EF_SUPPORT"),
        MaterialKind(
            "creep", "AC creep compliance", "ANALYSIS_TST_AC_CREEP_COMP", "ANALYSIS_TST_AC_CRCOM_SUPPORT"
        ),
        MaterialKind("wma_binder", "Warm-mix asphalt binder", "ANALYSIS_TST_WMA_BINDER", "ANALYSIS_TST_WMA_BINDER_SUPPORT"),
        MaterialKind("wma_mix", "Warm-mix asphalt mix", "ANALYSIS_TST_WMA_MIX", "ANALYSIS_TST_WMA_MIX_SUPPORT"),
    ]
}  # fmt: skip

LAYER_KINDS = ("asphalt", "asphalt_treated", "pcc", "pcc_treated", "unbound", "interlayer", "fabric")
ASPHALT_KINDS = ("asphalt", "asphalt_treated")

# Columns that identify a layer rather than describe its material.
IDENTITY = {
    "construction_no", "layer_no", "layer_type", "repr_thickness", "matl_code", "description",
    "project_layer_code", "record_status", "data_rec_id", "estar_link_group", "state_code", "shrp_id",
}  # fmt: skip

_ASPHALT_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("binder", ("dsr_", "absolute_visc", "kinematic_visc", "binder_spec")),
    ("gradation", ("_passing",)),
    ("volumetrics", ("air_voids", "asphalt_content", "max_spec", "bsg", "aggr_spec", "voids_")),
    ("strength_tests", ("idt_", "poisson_ratio_test")),
    ("thermal", ("thermal_", "heat_capacity", "sur_shortwave", "coef_thermal")),
]
_GROUPS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "asphalt": _ASPHALT_GROUPS,
    "asphalt_treated": _ASPHALT_GROUPS,
    "pcc": [
        ("strength_and_modulus", ("elastic_mod", "comp_strength", "modulus_of_rupture", "tensile_strength", "poisson_ratio")),
        ("mix", ("unit_wt", "water_cement")),
        ("thermal_and_shrinkage", ("coef_thermal", "thermal_", "heat_capacity", "sur_shortwave", "zero_stress", "shrinkage", "t_half")),
        ("reinforcement", ("bar_", "depth_to_reinforcement")),
    ],
    "unbound": [
        ("gradation", ("_passing",)),
        ("plasticity_and_classification", ("liquid_limit", "plastic_limit", "plasticity_index", "aashto_soil_class")),
        ("density_and_moisture", ("spec_gravity", "max_lab_dry", "optimum_lab")),
        ("stiffness", ("resilient_modulus", "poissons_ratio")),
        ("hydraulic", ("hydraulic_conductivity",)),
    ],
}  # fmt: skip


IDENTITY_COLUMNS = ("construction_no", "layer_no", "layer_type", "repr_thickness", "matl_code", "description")


def group_properties(kind: str, row: Row) -> dict[str, dict[str, Any]]:
    """Split a layer's non-empty property columns into engineering groups (binder, gradation, ...)."""
    rules = _GROUPS.get(kind, [])
    grouped: dict[str, dict[str, Any]] = {}
    for col, value in row.items():
        if col in IDENTITY or value is None:
            continue
        target = "properties"
        for name, needles in rules:
            if any(n in col for n in needles):
                target = name
                break
        grouped.setdefault(target, {})[col] = value
    return grouped


def read_layers(
    repo: Repository,
    kinds: tuple[str, ...] | list[str],
    ref: SectionRef,
    *,
    construction_no: int | None = None,
    layer_no: int | None = None,
    units: str = "stored",
    page: Page | None = None,
    grouped: bool = True,
    identity_only: bool = False,
    with_variability: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str], int]:
    """Layers of the given material kinds: (layers, fields, tables read, total).

    Layers come back newest construction event first, surface layer first (highest LAYER_NO).
    """
    layers: list[dict[str, Any]] = []
    metas: list[dict[str, dict[str, Any]]] = []
    tables: list[str] = []
    total = 0
    extra = [Cond("LAYER_NO", "eq", layer_no)] if layer_no is not None else []
    for key in kinds:
        kind = KINDS[key]
        rows, meta, n = read_section_rows(
            repo,
            kind.table,
            ref,
            construction_no=construction_no,
            extra=extra,
            order_by=[("CONSTRUCTION_NO", False), ("LAYER_NO", True)],
            units=units,
            page=None,
            columns=[c.upper() for c in IDENTITY_COLUMNS if repo.has_column(kind.table, c)] if identity_only else None,
        )
        tables.append(kind.table)
        metas.append(meta)
        total += n
        labels = {
            "layer_type": repo.code_labels("LAYER_TYPE"),
            "matl_code": repo.code_labels("MATERIAL"),
            "description": repo.code_labels("DESCRIPTION"),
        }
        quality: dict[tuple[Any, Any, str], dict[str, Any]] = {}
        if with_variability and kind.support:
            stats, smeta, _ = read_section_rows(
                repo, kind.support, ref, construction_no=construction_no, extra=extra,
                order_by=[("CONSTRUCTION_NO", False), ("LAYER_NO", False)], units="stored",
                columns=["CONSTRUCTION_NO", "LAYER_NO", "MATL_PROPERTY", "PROPERTY_COEFF_VARIATION", "SAMPLE_COUNT", "REP_CODE_SOURCE_VARIABILITY"],
            )  # fmt: skip
            metas.append(
                {"source_quality": smeta.get("rep_code_source_variability", {})}
                if smeta.get("rep_code_source_variability")
                else {}
            )
            tables.append(kind.support)
            for sr in stats:
                quality[(sr.get("construction_no"), sr.get("layer_no"), str(sr["matl_property"]).lower())] = {
                    k: v
                    for k, v in {
                        "n": sr.get("sample_count"),
                        "cv": sr.get("property_coeff_variation"),
                        "source_quality": sr.get("rep_code_source_variability"),
                    }.items()
                    if v is not None
                }
        for r in rows:
            layer: dict[str, Any] = {"material_class": kind.title}
            for col in (
                "construction_no",
                "layer_no",
                "layer_type",
                "repr_thickness",
                "matl_code",
                "description",
            ):
                if col in r:
                    layer[col] = r[col]
            for col, m in labels.items():
                code = r.get(col)
                if code is not None and str(code) in m:
                    layer[f"{col}_name"] = m[str(code)]
            if identity_only:
                pass
            elif grouped:
                layer["properties"] = group_properties(key, r)
            else:
                layer["properties"] = {c: v for c, v in r.items() if c not in IDENTITY and v is not None}
            if with_variability:
                shown = {c for grp in layer.get("properties", {}).values() if isinstance(grp, dict) for c in grp}
                layer["property_quality"] = {
                    prop: q
                    for (cn, ln, prop), q in quality.items()
                    if cn == layer.get("construction_no") and ln == layer.get("layer_no") and prop in shown
                }
            layers.append(layer)

    layers.sort(key=lambda x: (_num(x.get("construction_no")), -_num(x.get("layer_no"))))
    merged = fields.merge_fields(*metas)
    if page is not None:
        layers = layers[page.offset : page.offset + page.limit]
    return layers, merged, tables, total


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
