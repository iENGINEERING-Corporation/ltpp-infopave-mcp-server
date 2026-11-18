"""Which group of the tool catalogue each data-pack table belongs to."""

GROUPS = (
    "Sections",
    "Materials",
    "Construction features",
    "Performance",
    "Climate",
    "Traffic",
    "Maintenance and rehabilitation",
    "Reference",
)

_REFERENCE = {
    "CODES",
    "CODETYPES",
    "LTPPDD",
    "LTPPTD",
    "LDW_PPDB_DD",
    "LDW_PPDB_TD",
    "LDW_STANDARD_DATA_RELEASE",
}


def table_group(table: str) -> str:
    """The catalogue group (ARMAD materials, ARPED performance, ...) a table belongs to."""
    t = table.upper()
    if t in _REFERENCE:
        return "Reference"
    if t == "LDW_DP_GENERAL":
        return "Sections"
    if t.startswith("ANALYSIS_TST_"):
        return "Materials"
    if t.startswith("ANALYSIS_MNT_RHB_"):
        return "Maintenance and rehabilitation"
    if t in ("ANALYSIS_DRAINAGE", "ANALYSIS_JOINT", "ANALYSIS_SHOULDER"):
        return "Construction features"
    if t.startswith("ANALYSIS_") or t == "ANALYSIS":
        return "Performance"
    if t.startswith("MERRA_"):
        return "Climate"
    if t.startswith(("TRF_", "MEPDG_")):
        return "Traffic"
    return "Reference"
