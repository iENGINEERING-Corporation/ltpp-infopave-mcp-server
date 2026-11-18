"""Validated tool inputs. Tools keep flat, documented parameters and build these to validate them."""

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from infopave_mcp.config import DEFAULT_PAGE, MAX_PAGE
from infopave_mcp.models.geography import resolve_state

ClimateZone = Literal["wet-freeze", "wet-no-freeze", "dry-freeze", "dry-no-freeze"]
Region = Literal["North Atlantic", "North Central", "Southern", "Western"]
GpsSps = Literal["GPS", "SPS"]
TopLayer = Literal["AC", "PCC"]
MonitoringStatus = Literal["active", "out-of-study"]
Units = Literal["stored", "us", "si"]
PavementClass = Literal["flexible", "composite", "rigid"]
Measure = Literal["iri", "rutting", "cracking_ac", "cracking_jpcc", "cracking_crcp", "lte"]
TreatmentGroupBy = Literal[
    "climate_zone", "region", "state", "experiment_type", "top_layer", "functional_class", "gps_sps",
    "pavement_family", "treatment",
]  # fmt: skip
ClimateGroup = Literal["temperature", "precipitation", "humidity", "wind", "solar"]
ClimateVariable = Literal[
    "air_temperature_avg", "air_temperature_max", "air_temperature_min", "freeze_index", "freeze_thaw_days",
    "days_above_32c", "days_below_0c", "precipitation", "evaporation", "precipitation_days",
    "relative_humidity_avg", "time_of_wetness", "wind_speed_avg", "solar_radiation", "cloud_cover",
    "percent_sunshine",
]  # fmt: skip
LayerMaterial = Literal["asphalt", "asphalt_treated", "pcc", "pcc_treated", "unbound", "interlayer", "fabric"]
SupportMaterial = Literal[
    "asphalt", "asphalt_treated", "pcc", "pcc_treated", "unbound", "interlayer", "fabric",
    "creep", "wma_binder", "wma_mix",
]  # fmt: skip
MaterialGroupBy = Literal[
    "state",
    "region",
    "climate_zone",
    "experiment_type",
    "sps_project",
    "gps_sps",
    "top_layer",
    "functional_class",
    "construction_decade",
    "layer_type",
]
SectionGroupBy = Literal[
    "state",
    "region",
    "climate_zone",
    "experiment_type",
    "sps_project",
    "gps_sps",
    "top_layer",
    "functional_class",
    "monitoring_status",
    "construction_decade",
    "county",
    "lanes",
]

# Pavement families (from CODES / PAVEMENT_FAMILY) grouped the way engineers talk about them.
PAVEMENT_CLASSES: dict[str, tuple[str, ...]] = {
    "flexible": ("ACUB", "ACATB", "ACCTB", "ACTB"),  # asphalt concrete over a base
    "composite": ("ACPCC",),  # asphalt concrete over Portland cement concrete
    "rigid": ("JPCTB", "JPCUB", "JRCTB", "JRCUB", "CRCTB", "CRCUB", "PCPCC"),  # concrete pavements
}


def first_error(exc: ValidationError) -> ValueError:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    msg = str(err["msg"]).removeprefix("Value error, ")
    return ValueError(f"{loc}: {msg}" if loc else msg)


class Page(BaseModel):
    """Paging for lists. Page size is capped at MAX_PAGE; use offset to read further."""

    limit: int = DEFAULT_PAGE
    offset: int = 0
    requested_limit: int = DEFAULT_PAGE

    @classmethod
    def of(cls, limit: int = DEFAULT_PAGE, offset: int = 0) -> "Page":
        return cls(limit=max(1, min(limit, MAX_PAGE)), offset=max(0, offset), requested_limit=limit)

    @property
    def capped(self) -> bool:
        return self.requested_limit > self.limit


class DateRange(BaseModel):
    """An optional window on dates, given as years or full ISO dates (YYYY or YYYY-MM-DD)."""

    start: str | None = None
    end: str | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip()

    @property
    def start_date(self) -> str | None:
        return _as_date(self.start, end=False)

    @property
    def end_date(self) -> str | None:
        return _as_date(self.end, end=True)

    @model_validator(mode="after")
    def _ordered(self) -> "DateRange":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start must not be after end.")
        return self


def _as_date(value: str | None, *, end: bool) -> str | None:
    if value is None:
        return None
    if len(value) == 4 and value.isdigit():
        return f"{value}-12-31" if end else f"{value}-01-01"
    parts = value.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[0]) == 4:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    raise ValueError(f"'{value}' is not a year (2015) or a date (2015-06-30).")


def make_range(start: str | int | None, end: str | int | None) -> DateRange:
    try:
        return DateRange(start=None if start is None else str(start), end=None if end is None else str(end))
    except ValidationError as exc:
        raise first_error(exc) from None


class SectionFilter(BaseModel):
    """Which test sections to include. Every field is optional and combined with AND."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)  # a mistyped key is an error, not ignored

    states: list[str] | None = Field(default=None, validation_alias=AliasChoices("states", "state"))
    state_codes: list[int] | None = None  # filled in from `states`
    region: Region | None = None
    climate_zone: ClimateZone | None = None
    experiment: str | None = None
    gps_sps: GpsSps | None = None
    top_layer: TopLayer | None = None
    functional_class: str | None = None
    monitoring_status: MonitoringStatus | None = None
    county: str | None = None
    constructed_after: int | None = None
    constructed_before: int | None = None
    near_latitude: float | None = None
    near_longitude: float | None = None
    radius_km: float = 25

    @field_validator("states", mode="before")
    @classmethod
    def _states_list(cls, v: Any) -> Any:
        if v is None or v == "" or v == []:
            return None
        return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]

    @field_validator("experiment", "functional_class", "county", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "SectionFilter":
        if self.states:
            self.state_codes = sorted({resolve_state(s) for s in self.states})
        if (self.near_latitude is None) != (self.near_longitude is None):
            raise ValueError("Provide both near_latitude and near_longitude, or neither.")
        if self.near_latitude is not None and not -90 <= self.near_latitude <= 90:
            raise ValueError("near_latitude must be between -90 and 90.")
        if self.near_longitude is not None and not -180 <= self.near_longitude <= 180:
            raise ValueError("near_longitude must be between -180 and 180.")
        if self.radius_km <= 0:
            raise ValueError("radius_km must be positive.")
        if (
            self.constructed_after is not None
            and self.constructed_before is not None
            and self.constructed_after > self.constructed_before
        ):
            raise ValueError("constructed_after must not be later than constructed_before.")
        return self

    @property
    def has_near(self) -> bool:
        return self.near_latitude is not None

    @classmethod
    def create(cls, state: str | list[str] | None = None, **kwargs: Any) -> "SectionFilter":
        """Build and validate, raising a plain ValueError with a readable message."""
        try:
            return cls(states=state, **kwargs)  # type: ignore[arg-type]
        except ValidationError as exc:
            raise first_error(exc) from None
        except ValueError:
            raise

    def is_empty(self) -> bool:
        return not any(
            [
                self.state_codes, self.region, self.climate_zone, self.experiment, self.gps_sps,
                self.top_layer, self.functional_class, self.monitoring_status, self.county,
                self.constructed_after, self.constructed_before, self.has_near,
            ]
        )  # fmt: skip


class SectionGroup(SectionFilter):
    """A named group of sections, for comparing one group against another."""

    label: str | None = None
    pavement_class: PavementClass | None = None
    min_ac_thickness_in: float | None = None
    max_ac_thickness_in: float | None = None

    def title(self, fallback: str) -> str:
        return self.label or fallback


def make_group(group: SectionGroup | dict[str, Any] | None, fallback: str) -> SectionGroup:
    """Validate a group given as a model or a plain dict (what an MCP client sends)."""
    try:
        if group is None:
            return SectionGroup(label=fallback)
        if isinstance(group, SectionGroup):
            return group
        return SectionGroup(**dict(group))
    except ValidationError as exc:
        raise first_error(exc) from None
