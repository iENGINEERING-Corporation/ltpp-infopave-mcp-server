"""Build the Envelope every tool returns."""

from collections.abc import Iterable
from typing import Any

from infopave_mcp.models import Envelope, Page
from infopave_mcp.repository import get_repository
from infopave_mcp.services import caveats as cv
from infopave_mcp.services.topics import public_title, scrub

REFERENCE_TABLES = ("CODES", "LDW_PPDB_DD")


def _is_sample() -> bool:
    try:
        return bool(get_repository().manifest().get("sample", False))
    except (FileNotFoundError, NotImplementedError):
        return False


def respond(
    data: Any,
    *,
    sources: Iterable[str],
    caveats: Iterable[str] = (),
    decoded: bool = False,
    page: Page | None = None,
    total_count: int | None = None,
    returned: int | None = None,
) -> Envelope:
    """Wrap a result with the data release, sources and caveats. Table names are internal: `sources` carries
    dataset titles, and any table name in the data or caveats is replaced by its title.

    decoded=True adds the reference tables (CODES, LDW_PPDB_DD) used to give units and code meanings.
    Pass page + total_count + returned for paged lists so next_offset is set.
    """
    repo = get_repository()
    names = [public_title(t) for t in [*sources, *(REFERENCE_TABLES if decoded else ())]]  # never table names
    notes = list(caveats)
    if page is not None:
        notes += cv.page_capped(page)
    if _is_sample():
        notes.append(cv.SAMPLE_PACK)
    return Envelope.build(
        scrub(data),
        data_release=str(repo.data_release()["label"]),
        sources=names,
        caveats=scrub(notes),
        total_count=total_count,
        offset=page.offset if page else 0,
        returned=returned,
    )
