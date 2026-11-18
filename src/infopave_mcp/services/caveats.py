"""Warnings attached to answers. Each is a statement about the data pack or the method, so the AI can pass
it on to the user. Keep them factual: say what is known and what is not documented."""

from infopave_mcp.models.inputs import Page

SECTION_KEY = (
    "A test section is identified by STATE_CODE plus SHRP_ID (SHRP_ID alone repeats across states). "
    "CONSTRUCTION_NO numbers the construction events (changes in pavement structure) on a section."
)
UNITS_AS_STORED = (
    "Values are in the units stored in the data pack, which differ by column (see `fields`). "
    "Pass units='us' or units='si' to convert."
)
UNITS_CONVERTED = (
    "Values were converted from the stored units (original unit in `fields`); columns with no known "
    "conversion are left as stored."
)
FLAGS = (
    "A flag marks a value LTPP considers a potential anomaly (meaning in `fields`). Flagged values are "
    "included, not removed."
)
CLIMATE_SCOPE = (
    "Climate data is MERRA-2 reanalysis for the grid cell serving the section (625 cells serve all 2,581 "
    "sections), 1980 to 2025. Only yearly and monthly summaries are in the pack; daily and hourly data are "
    "not available."
)
CLIMATE_MODELLED = "Climate values are modelled grid-cell estimates, not measurements taken at the section."
CELLS_SHARED = "Several sections can share one climate grid cell, so their climate values are identical."
IRI_RUNS = "IRI and MRI are averaged over the profiler runs of each visit."
DISTRESS_TABLES = (
    "Distress is stored in three tables by pavement type (asphalt, jointed concrete, continuously reinforced "
    "concrete). A section appears in more than one only if its structure changed."
)
AGE_BASIS = "Age is measured from the section's recorded date of construction."
OBSERVATIONAL = (
    "Before/after comparisons are observational: treatments were not randomly assigned, and traffic, "
    "climate, structure and prior condition are not controlled for. Do not read a change as the effect of "
    "the treatment alone."
)
INTERVAL_RULE = (
    "The 'before' measurement is the last visit on or before the treatment date and the 'after' measurement "
    "the first visit after it. A pair is used only where the treatment record gives a valid interval (in "
    "months) for that data type, meaning the same pavement structure was measured on both sides."
)
CRCP_NOTES_OMITTED = (
    "The free-text OTHER column of the CRCP distress data (127 survey notes) is not served: it contains a byte that "
    "is not valid UTF-8 in the data pack and cannot be read. All other CRCP columns are complete."
)
TRAFFIC_SOURCES = "Traffic values may be monitored or estimated; the source columns say which (meanings in `fields`)."
MATERIAL_REPRESENTATIVE = (
    "Material properties are representative values for a layer. Use get_property_variability for the spread "
    "and the quality of the source of each value."
)
LTE_SUMMARISED = "Load transfer efficiency has many drops per test date; results are summarised by test date."
DISTANCE_NOTE = "Distances are straight-line (great-circle) kilometres."
SAMPLE_PACK = (
    "This is a SAMPLE of the LTPP data pack, not the full database: counts and averages describe the sample only."
)
TREATMENT_COUNTS = (
    "Treatment-effect results use only treatments with a valid before and after measurement; the number used "
    "is reported with every result."
)
CONSTRUCTION_BASIS = (
    "Thickness filters use the total thickness of asphalt layers (AC and AC-treated) in the section's most "
    "recent construction event that has asphalt layers."
)
REPRESENTATIVE_TRAFFIC = (
    "Representative traffic values summarise the whole monitoring period for the section; use "
    "get_traffic_trend for year-by-year values."
)


def page_capped(page: Page) -> list[str]:
    """A note when the caller asked for more rows per page than allowed."""
    if page.capped:
        return [f"Page size is capped at {page.limit} rows; use next_offset to read further."]
    return []


def units_note(units: str) -> str:
    return UNITS_CONVERTED if units in ("us", "si") else UNITS_AS_STORED


def small_sample(n: int, threshold: int = 10) -> list[str]:
    if n < threshold:
        return [f"Only {n} treatment(s) had a valid before and after measurement, so this is a small sample."]
    return []


RECORDS_NOT_SECTIONS = (
    "Counts are of table rows (records). A section normally has many rows, so use the `sections` count for "
    "'how many sections'. A record can repeat across construction events."
)
RANKING_NOTE = (
    "Rankings use every matching value, including values LTPP flagged as possible anomalies, and sections or "
    "records with no value are left out. Ties are broken by section key."
)
