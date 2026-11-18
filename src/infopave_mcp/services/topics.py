"""The public names of the data: topics and dataset titles.

Table names are internal. Nothing an AI client can see (tool inputs, answers, sources, resources, errors)
names a table. Instead:
  * data-wide tools take a *topic* (a plain-language key such as "roughness" or "treatments");
  * `sources` in every response lists dataset titles ("Section-level roughness (IRI)"), not tables;
  * scrub() removes any table name that slips into text (for example from the data dictionary).
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Topic:
    key: str
    table: str  # internal
    title: str  # public


def _t(key: str, table: str, title: str) -> Topic:
    return Topic(key, table, title)


TOPICS: tuple[Topic, ...] = (
    _t("sections", "LDW_DP_GENERAL", "Test section inventory"),
    # performance
    _t("roughness", "ANALYSIS_IRI", "Section-level roughness (IRI and MRI)"),
    _t("rutting", "ANALYSIS_RUTTING", "Section-level rut depth"),
    _t("cracking_asphalt", "ANALYSIS_DIS_AC", "Cracking and distress on asphalt pavements"),
    _t("cracking_jointed_concrete", "ANALYSIS_DIS_JPCC", "Cracking and distress on jointed concrete pavements"),
    _t("distress_crcp", "ANALYSIS_DIS_CRCP", "Distress on continuously reinforced concrete pavements"),
    _t("load_transfer", "ANALYSIS_LTE", "Joint and crack load transfer efficiency"),
    _t("dowel_scans", "ANALYSIS_MIT", "Dowel bar scan (MIT) results"),
    # construction features
    _t("drainage", "ANALYSIS_DRAINAGE", "Subsurface drainage design"),
    _t("joints", "ANALYSIS_JOINT", "Concrete joint design"),
    _t("shoulders", "ANALYSIS_SHOULDER", "Shoulder structure and condition"),
    # maintenance and rehabilitation
    _t("treatments", "ANALYSIS_MNT_RHB_SUMMARY", "Maintenance and rehabilitation events (summary)"),
    _t("treatments_asphalt_spot", "ANALYSIS_MNT_RHB_AC_SPOT", "Asphalt spot maintenance details"),
    _t("treatments_asphalt_surface", "ANALYSIS_MNT_RHB_AC_SURFACE", "Asphalt surface treatment details"),
    _t("treatments_concrete_spot", "ANALYSIS_MNT_RHB_PCC_SPOT", "Concrete spot maintenance details"),
    _t("treatments_concrete_surface", "ANALYSIS_MNT_RHB_PCC_SURFACE", "Concrete surface treatment details"),
    _t("treatments_subdrainage", "ANALYSIS_MNT_RHB_SUBDRAINAGE", "Subdrainage maintenance details"),
    # materials
    _t("asphalt_layers", "ANALYSIS_TST_AC", "Asphalt layer material properties"),
    _t("asphalt_treated_layers", "ANALYSIS_TST_ACT", "Asphalt-treated layer material properties"),
    _t("asphalt_creep_compliance", "ANALYSIS_TST_AC_CREEP_COMP", "Asphalt creep compliance"),
    _t("asphalt_dynamic_modulus", "ANALYSIS_TST_AC_ESTAR", "Asphalt dynamic modulus (E*)"),
    _t("concrete_layers", "ANALYSIS_TST_PCC", "Concrete layer material properties"),
    _t("concrete_treated_layers", "ANALYSIS_TST_PCT", "Concrete-treated layer material properties"),
    _t("unbound_layers", "ANALYSIS_TST_UNBOUND", "Unbound layer material properties"),
    _t("interlayers", "ANALYSIS_TST_TR", "Interlayer and treatment layer properties"),
    _t("fabric_layers", "ANALYSIS_TST_EF", "Engineering fabric layer properties"),
    _t("warm_mix_binder", "ANALYSIS_TST_WMA_BINDER", "Warm-mix asphalt binder (SPS-10)"),
    _t("warm_mix_mix", "ANALYSIS_TST_WMA_MIX", "Warm-mix asphalt mix (SPS-10)"),
    _t("asphalt_layers_support", "ANALYSIS_TST_AC_SUPPORT", "Asphalt layer supporting statistics"),
    _t("asphalt_treated_layers_support", "ANALYSIS_TST_ACT_SUPPORT", "Asphalt-treated layer supporting statistics"),
    _t("asphalt_creep_support", "ANALYSIS_TST_AC_CRCOM_SUPPORT", "Asphalt creep compliance supporting statistics"),
    _t("concrete_layers_support", "ANALYSIS_TST_PCC_SUPPORT", "Concrete layer supporting statistics"),
    _t("concrete_treated_layers_support", "ANALYSIS_TST_PCT_SUPPORT", "Concrete-treated layer supporting statistics"),
    _t("unbound_layers_support", "ANALYSIS_TST_UNBOUND_SUPPORT", "Unbound layer supporting statistics"),
    _t("interlayers_support", "ANALYSIS_TST_TR_SUPPORT", "Interlayer supporting statistics"),
    _t("fabric_layers_support", "ANALYSIS_TST_EF_SUPPORT", "Engineering fabric supporting statistics"),
    _t("warm_mix_binder_support", "ANALYSIS_TST_WMA_BINDER_SUPPORT", "Warm-mix binder supporting statistics"),
    _t("warm_mix_mix_support", "ANALYSIS_TST_WMA_MIX_SUPPORT", "Warm-mix mix supporting statistics"),
    # climate
    _t("climate_cells", "MERRA_GRID_SECTION", "Climate grid cell to section link"),
    _t("climate_binder_temperatures", "MERRA_BIND_TEMP_SUMMARY", "Yearly binder-grade temperature extremes"),
    _t("climate_temperature_yearly", "MERRA_TEMP_YEAR", "Yearly air temperature (MERRA-2)"),
    _t("climate_temperature_monthly", "MERRA_TEMP_MONTH", "Monthly air temperature (MERRA-2)"),
    _t("climate_precipitation_yearly", "MERRA_PRECIP_YEAR", "Yearly precipitation (MERRA-2)"),
    _t("climate_precipitation_monthly", "MERRA_PRECIP_MONTH", "Monthly precipitation (MERRA-2)"),
    _t("climate_humidity_yearly", "MERRA_HUMID_YEAR", "Yearly humidity (MERRA-2)"),
    _t("climate_humidity_monthly", "MERRA_HUMID_MONTH", "Monthly humidity (MERRA-2)"),
    _t("climate_wind_yearly", "MERRA_WIND_YEAR", "Yearly wind (MERRA-2)"),
    _t("climate_wind_monthly", "MERRA_WIND_MONTH", "Monthly wind (MERRA-2)"),
    _t("climate_solar_yearly", "MERRA_SOLAR_YEAR", "Yearly solar radiation (MERRA-2)"),
    _t("climate_solar_monthly", "MERRA_SOLAR_MONTH", "Monthly solar radiation (MERRA-2)"),
    # traffic
    _t("traffic_representative", "TRF_REP", "Representative traffic parameters"),
    _t("traffic_trend", "TRF_TREND", "Annual traffic trend (AADTT and ESAL)"),
    _t("traffic_monthly_factors", "TRF_MEPDG_MONTH_ADJ_FACTR", "Monthly traffic adjustment factors"),
    _t("traffic_hourly_distribution", "TRF_MEPDG_HOURLY_DIST", "Hourly traffic distribution"),
    _t("axle_load_distribution", "MEPDG_AXLE_LOAD_DIST_FACTOR", "Axle load distribution factors"),
    _t("axles_per_truck", "MEPDG_AXLE_PER_TRUCK", "Axles per truck by vehicle class"),
    _t("truck_volume_parameters", "MEPDG_TRUCK_VOL_PARAMETERS", "Truck volume and class parameters"),
)

# Reference tables: they appear in `sources` (as the code lists and dictionary) but are not topics.
_REFERENCE_TITLES = {
    "CODES": "Code lists",
    "CODETYPES": "Code type list",
    "LTPPDD": "LTPP data dictionary",
    "LTPPTD": "LTPP table dictionary",
    "LDW_PPDB_DD": "InfoPave data dictionary",
    "LDW_PPDB_TD": "InfoPave table dictionary",
    "LDW_STANDARD_DATA_RELEASE": "Data release list",
}

TOPIC_KEYS: tuple[str, ...] = tuple(t.key for t in TOPICS)
_BY_KEY = {t.key: t for t in TOPICS}
_TITLE_BY_TABLE = {**{t.table: t.title for t in TOPICS}, **_REFERENCE_TITLES}


def topic(key: str) -> Topic:
    """The topic for a key (case and separators are forgiven); the error lists the valid keys."""
    norm = re.sub(r"[\s-]+", "_", str(key).strip().lower())
    if norm in _BY_KEY:
        return _BY_KEY[norm]
    close = [k for k in TOPIC_KEYS if norm and (norm in k or k in norm)][:6]
    hint = f" Closest: {', '.join(close)}." if close else ""
    raise ValueError(f"Unknown topic '{key}'.{hint} Call get_data_overview with no topic to list the topics.")


def key_for_table(table: str) -> str | None:
    """The topic key of a table, or None for reference tables."""
    return next((t.key for t in TOPICS if t.table == table.upper()), None)


def public_title(table: str) -> str:
    """The plain-language name of a table, for `sources`."""
    return _TITLE_BY_TABLE.get(table.upper(), "InfoPave data")


# --- scrubbing -----------------------------------------------------------------------------------------------
# Table names that contain an underscore are matched exactly (upper case); the one-word names (CODES ...) are
# ordinary words, so they are left alone.
_NAMES = sorted((n for n in _TITLE_BY_TABLE if "_" in n), key=len, reverse=True)
_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, _NAMES)) + r")(?![A-Za-z0-9_])", re.I)


def scrub_text(text: str) -> str:
    return _PATTERN.sub(lambda m: public_title(m.group(1)), text)


def scrub(value: Any) -> Any:
    """Replace table names inside any string of a nested result with the public dataset title."""
    if isinstance(value, str):
        return scrub_text(value) if "_" in value else value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v) for v in value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value
