"""Find the test section a caller means.

A section is identified by STATE_CODE plus SHRP_ID: SHRP_ID alone repeats across states (1,028 distinct
SHRP_IDs for 2,581 sections).
"""

from dataclasses import dataclass
from typing import Any

from infopave_mcp.models.geography import resolve_state
from infopave_mcp.repository.base import Repository, Row


@dataclass(frozen=True)
class SectionRef:
    state_code: int
    state: str
    shrp_id: str
    record: Row

    def key(self) -> dict[str, Any]:
        """The identifying block put at the top of per-section results."""
        r = self.record
        return {
            "state": self.state,
            "state_code": self.state_code,
            "shrp_id": self.shrp_id,
            "county": r.get("county_name"),
            "route": _route(r),
            "direction": r.get("direction_detail"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
        }


def _route(r: Row) -> str | None:
    detail, number = r.get("route_detail"), r.get("route_no")
    if detail and number:
        return f"{detail} {number}".strip()
    return str(number) if number else None


def normalize_shrp_id(value: str) -> str:
    ident = str(value).strip().upper()
    if not ident:
        raise ValueError("shrp_id must not be empty.")
    return ident.zfill(4) if ident.isdigit() and len(ident) < 4 else ident


def resolve_section(repo: Repository, state: str, shrp_id: str) -> SectionRef:
    """Look up one section by state (name, abbreviation or code) and SHRP_ID."""
    code = resolve_state(state)
    ident = normalize_shrp_id(shrp_id)
    record = repo.find_section(code, ident)
    if record is None:
        similar = repo.similar_section_ids(code, ident)
        hint = f" Sections in that state include: {', '.join(similar)}." if similar else ""
        raise ValueError(f"No test section with SHRP_ID '{ident}' in {state}.{hint}")
    return SectionRef(code, str(record["state_name"]), ident, record)
