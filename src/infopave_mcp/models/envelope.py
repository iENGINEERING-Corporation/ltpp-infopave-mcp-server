"""The response envelope every tool returns, so any number can be traced to where it came from."""

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    data: Any = Field(description="The result.")
    data_release: str = Field(description="The LTPP Standard Data Release (SDR) the data comes from.")
    sources: list[str] = Field(description="Data-pack tables the answer was read from.")
    caveats: list[str] = Field(default_factory=list, description="Warnings that must be passed on to the user.")
    total_count: int | None = Field(default=None, description="Rows matching, for paged lists.")
    next_offset: int | None = Field(default=None, description="Pass as offset to get the next page.")

    @classmethod
    def build(
        cls,
        data: Any,
        *,
        data_release: str,
        sources: Iterable[str],
        caveats: Iterable[str] = (),
        total_count: int | None = None,
        offset: int = 0,
        returned: int | None = None,
    ) -> "Envelope":
        """Wrap a result. For paged lists pass total_count, offset and returned to get next_offset."""
        next_offset = None
        if total_count is not None and returned is not None and offset + returned < total_count:
            next_offset = offset + returned
        return cls(
            data=data,
            data_release=data_release,
            sources=list(dict.fromkeys(sources)),
            caveats=list(dict.fromkeys(caveats)),
            total_count=total_count,
            next_offset=next_offset,
        )
