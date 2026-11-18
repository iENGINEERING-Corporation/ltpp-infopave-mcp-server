"""Maintenance and rehabilitation: treatment codes, surface vs spot treatments, before/after pairs."""

from typing import Any

from infopave_mcp.repository.base import Repository, Row
from infopave_mcp.services.units import conversion_for, convert_number

# Words in a MAINT_WORK label that mark a surface treatment: one that changes the pavement structure, for which
# LTPP leaves the "after" interval empty by design (the structure after is a new construction event).
SURFACE_WORDS = ("overlay", "mill", "grind", "reconstruct", "fractur", "scarif")


def labels(repo: Repository) -> dict[str, str]:
    return repo.code_labels("MAINT_WORK")


def surface_codes(repo: Repository) -> list[str]:
    return [c for c, text in labels(repo).items() if any(w in text.lower() for w in SURFACE_WORDS)]


def is_surface(repo: Repository, code: Any) -> bool:
    return str(code) in set(surface_codes(repo))


def resolve_treatments(repo: Repository, spec: int | str | list[int | str] | None) -> list[str] | None:
    """Turn a treatment code, a word (\"overlay\") or a list of either into MAINT_WORK codes.

    None means all treatments. A word matches every treatment whose name contains it.
    """
    if spec is None or spec == "" or spec == []:
        return None
    items = spec if isinstance(spec, list) else [spec]
    known = labels(repo)
    codes: list[str] = []
    for item in items:
        text = str(item).strip()
        if text in known:
            codes.append(text)
            continue
        hits = [c for c, label in known.items() if text.lower() in label.lower()]
        if not hits:
            examples = ", ".join(f"{c} {known[c]}" for c in list(known)[:6])
            raise ValueError(
                f"No treatment matches '{text}'. Use a code or a word from the treatment name, e.g. {examples}."
            )
        codes.extend(hits)
    return list(dict.fromkeys(codes))


def describe_treatments(repo: Repository, codes: list[str] | None) -> list[dict[str, Any]]:
    known = labels(repo)
    surface = set(surface_codes(repo))
    use = codes if codes is not None else list(known)
    return [
        {
            "maint_work": c,
            "treatment": known.get(c, c),
            "type": "surface" if c in surface else "spot / maintenance",
        }
        for c in use
    ]


def add_treatment_names(repo: Repository, rows: list[Row], key: str = "maint_work") -> None:
    """Add a readable `treatment` and `treatment_type` next to each MAINT_WORK code, in place."""
    known = labels(repo)
    surface = set(surface_codes(repo))
    for r in rows:
        code = r.get(key)
        if code is not None:
            r["treatment"] = known.get(str(code), str(code))
            r["treatment_type"] = "surface" if str(code) in surface else "spot / maintenance"


def convert_pair_values(unit: str | None, units: str, rows: list[Row]) -> str | None:
    """Convert before/after values in place to the requested unit system; return the unit shown."""
    conv = conversion_for(unit, units)
    if conv is None:
        return unit
    for r in rows:
        for k in ("before_value", "after_value"):
            r[k] = convert_number(r.get(k), conv)
    return conv.to_unit
