"""Unit conversion between SI and US customary.

The data dictionary says which unit each column is *stored* in (it varies: IRI is m/km, layer thickness is
inches). Its own conversion factors are inconsistent in places (the same unit converts to two different
targets), so conversions here use a fixed table of exact factors for the common units. Anything not in the
table is left as stored and reported, never guessed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

M2_PER_FT2 = 0.09290304


@dataclass(frozen=True)
class Conversion:
    system: str  # the system the *stored* unit belongs to: "si" or "us"
    to_unit: str
    convert: Callable[[float], float]


def _scale(factor: float) -> Callable[[float], float]:
    return lambda x: x * factor


_TABLE: dict[str, Conversion] = {}


def _add(unit: str, system: str, to_unit: str, factor: float) -> None:
    _TABLE[unit] = Conversion(system, to_unit, _scale(factor))


# SI -> US
_add("mm", "si", "in", 1 / 25.4)
_add("cm", "si", "in", 1 / 2.54)
_add("m", "si", "ft", 1 / 0.3048)
_add("km", "si", "mi", 1 / 1.609344)
_add("microns", "si", "mils", 1 / 25.4)
_add("kPa", "si", "psi", 0.1450377)
_add("MPa", "si", "ksi", 0.1450377)
_add("GPa", "si", "ksi", 145.0377)
_add("kg/cu m", "si", "pcf", 0.06242797)
_add("sq m", "si", "sq ft", 1 / M2_PER_FT2)
_add("m/km", "si", "in/mi", 63.36)
_add("m/s", "si", "mph", 2.236936)
_add("km/h", "si", "mph", 0.6213712)
_add("N", "si", "lbf", 0.2248089)
_add("kN", "si", "lbf", 224.8089)
_add("kg", "si", "lb", 2.204623)
_add("deg C degree days", "si", "deg F degree days", 1.8)
_TABLE["deg C"] = Conversion("si", "deg F", lambda c: c * 9 / 5 + 32)

# US -> SI
_add("in", "us", "mm", 25.4)
_add("ft", "us", "m", 0.3048)
_add("mi", "us", "km", 1.609344)
_add("mils", "us", "microns", 25.4)
_add("psi", "us", "kPa", 6.894757)
_add("ksi", "us", "MPa", 6.894757)
_add("pcf", "us", "kg/cu m", 16.01846)
_add("sq ft", "us", "sq m", M2_PER_FT2)
_add("in/mi", "us", "m/km", 1 / 63.36)
_add("mph", "us", "km/h", 1.609344)
_add("lbf", "us", "N", 4.448222)
_add("lb", "us", "kg", 0.4535924)
_add("1/16 in", "us", "mm", 1.5875)
_add("deg F degree days", "us", "deg C degree days", 1 / 1.8)
_TABLE["deg F"] = Conversion("us", "deg C", lambda f: (f - 32) * 5 / 9)


def conversion_for(unit: str | None, target: str) -> Conversion | None:
    """The conversion to apply to a column stored in `unit` when `target` ("us" or "si") is wanted."""
    if not unit or target not in ("us", "si"):
        return None
    conv = _TABLE.get(unit)
    return conv if conv is not None and conv.system != target else None


def convert_number(value: Any, conv: Conversion) -> Any:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    out = conv.convert(float(value))
    return round(out, 2) if abs(out) >= 1000 else round(out, 4)


def usd(value: float | None) -> int | None:
    """Whole US dollars, or None."""
    return None if value is None else round(value)


def pct(part: float, whole: float, digits: int = 2) -> float | None:
    """Percentage of whole, or None when whole is zero."""
    return round(100.0 * part / whole, digits) if whole else None
