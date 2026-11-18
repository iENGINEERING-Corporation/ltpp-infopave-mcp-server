"""The performance measures that group comparisons and before/after analyses can use."""

from infopave_mcp.models.query import MeasureSpec

MEASURES: dict[str, MeasureSpec] = {
    m.key: m
    for m in [
        MeasureSpec(
            "iri", "Mean roughness index (MRI)", "ANALYSIS_IRI", "MRI", "VISIT_DATE", ("MRI_FLAG",), "profile"
        ),
        MeasureSpec(
            "rutting", "Maximum mean rut depth", "ANALYSIS_RUTTING", "MAX_MEAN_DEPTH_1_8", "SURVEY_DATE",
            ("MAX_MEAN_DEPTH_1_8_FLAG",), "profile",
        ),
        MeasureSpec(
            "cracking_ac", "Fatigue cracking, asphalt (MEPDG, % of area)", "ANALYSIS_DIS_AC",
            "MEPDG_CRACKING_PERCENT_AC", "SURVEY_DATE", (), "distress",
        ),
        MeasureSpec(
            "cracking_jpcc", "Cracked slabs, jointed concrete (MEPDG, %)", "ANALYSIS_DIS_JPCC",
            "MEPDG_CRACKING_PERCENT_JPCC", "SURVEY_DATE", (), "distress",
        ),
        MeasureSpec(
            "cracking_crcp", "Punchouts, continuously reinforced concrete (MEPDG, per mile)",
            "ANALYSIS_DIS_CRCP", "MEPDG_PUNCHOUTS_CRCP", "SURVEY_DATE", (), "distress",
        ),
        MeasureSpec(
            "lte", "Load transfer efficiency", "ANALYSIS_LTE", "LOAD_TRANSFER_EFFICIENCY", "TEST_DATE",
            ("LTE_FLAG",), "deflection",
        ),
    ]
}  # fmt: skip

MeasureKey = str
