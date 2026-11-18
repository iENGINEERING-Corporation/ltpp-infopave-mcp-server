"""Climate (ARCLD): MERRA-2 yearly and monthly tables, the grid cell serving each section."""

from dataclasses import dataclass
from typing import Any

from infopave_mcp.models import Cond, Select
from infopave_mcp.repository.base import Repository, Row
from infopave_mcp.services.sections import SectionRef

GRID = "MERRA_GRID_SECTION"
BINDER = "MERRA_BIND_TEMP_SUMMARY"

# climate variable group -> (yearly table, monthly table, columns shown by default)
GROUPS: dict[str, tuple[str, str, list[str]]] = {
    "temperature": (
        "MERRA_TEMP_YEAR", "MERRA_TEMP_MONTH",
        ["temp_avg", "temp_max", "temp_min", "freeze_index", "freeze_thaw", "days_above_32_c", "days_below_0_c"],
    ),
    "precipitation": ("MERRA_PRECIP_YEAR", "MERRA_PRECIP_MONTH", ["precipitation", "evaporation", "precip_days"]),
    "humidity": (
        "MERRA_HUMID_YEAR", "MERRA_HUMID_MONTH",
        ["rel_hum_avg_avg", "rel_hum_avg_max", "rel_hum_avg_min", "humidity_days", "time_of_wetness"],
    ),
    "wind": (
        "MERRA_WIND_YEAR", "MERRA_WIND_MONTH",
        ["wind_velocity_avg", "wind_velocity_max", "wind_velocity_min", "wind_days", "avg_pwd"],
    ),
    "solar": (
        "MERRA_SOLAR_YEAR", "MERRA_SOLAR_MONTH",
        ["shortwave_surface", "shortwave_toa", "cloud_cover_avg", "percent_sunshine_avg", "solar_days", "albedo", "emissivity"],
    ),
}  # fmt: skip
KEYS = {"merra_id", "year", "month"}


@dataclass(frozen=True)
class ClimateVar:
    key: str
    title: str
    column: str  # upper-case column name, present in both the yearly and the monthly table
    group: str


# Variables that can be compared between groups of sections.
VARS: dict[str, ClimateVar] = {
    v.key: v
    for v in [
        ClimateVar("air_temperature_avg", "Average air temperature", "TEMP_AVG", "temperature"),
        ClimateVar("air_temperature_max", "Maximum air temperature", "TEMP_MAX", "temperature"),
        ClimateVar("air_temperature_min", "Minimum air temperature", "TEMP_MIN", "temperature"),
        ClimateVar("freeze_index", "Freezing index", "FREEZE_INDEX", "temperature"),
        ClimateVar("freeze_thaw_days", "Freeze-thaw days", "FREEZE_THAW", "temperature"),
        ClimateVar("days_above_32c", "Days above 32 C", "DAYS_ABOVE_32_C", "temperature"),
        ClimateVar("days_below_0c", "Days below 0 C", "DAYS_BELOW_0_C", "temperature"),
        ClimateVar("precipitation", "Precipitation", "PRECIPITATION", "precipitation"),
        ClimateVar("evaporation", "Evaporation", "EVAPORATION", "precipitation"),
        ClimateVar("precipitation_days", "Days with precipitation", "PRECIP_DAYS", "precipitation"),
        ClimateVar("relative_humidity_avg", "Average relative humidity", "REL_HUM_AVG_AVG", "humidity"),
        ClimateVar("time_of_wetness", "Time of wetness", "TIME_OF_WETNESS", "humidity"),
        ClimateVar("wind_speed_avg", "Average wind speed", "WIND_VELOCITY_AVG", "wind"),
        ClimateVar("solar_radiation", "Surface shortwave radiation", "SHORTWAVE_SURFACE", "solar"),
        ClimateVar("cloud_cover", "Cloud cover", "CLOUD_COVER_AVG", "solar"),
        ClimateVar("percent_sunshine", "Percent sunshine", "PERCENT_SUNSHINE_AVG", "solar"),
    ]
}  # fmt: skip


def grid_cell(repo: Repository, ref: SectionRef) -> Row:
    rows, _ = repo.select(
        Select(
            GRID,
            where=[Cond("STATE_CODE", "eq", ref.state_code), Cond("SHRP_ID", "eq", ref.shrp_id)],
        )
    )
    if not rows:
        raise ValueError(f"No climate grid cell is recorded for {ref.state} section {ref.shrp_id}.")
    return rows[0]


def cell_summary(cell: Row) -> dict[str, Any]:
    return {
        "merra_id": cell["merra_id"],
        "cell_latitude": cell.get("latitude"),
        "cell_longitude": cell.get("longitude"),
        "cell_elevation_m": cell.get("elevation"),
    }


def columns_for(repo: Repository, table: str, group: str, detail: str) -> list[str]:
    """Upper-case column names to read for a variable group at the requested level of detail."""
    if detail == "full":
        return [c.upper() for c in (r["column_name"] for r in repo.table_columns(table)) if c not in {"merra_id"}]
    wanted = ["year", "month", *GROUPS[group][2]]
    return [c.upper() for c in wanted if repo.has_column(table, c)]
