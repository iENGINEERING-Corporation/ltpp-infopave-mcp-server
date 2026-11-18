"""Knowledge base shipped with the server: the AI system prompt and the tool catalogue."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from infopave_mcp.kb.catalog import GROUPS, table_group

_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return (_DIR / "system_prompt.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def tool_catalog() -> dict[str, Any]:
    """The planned tools by group, with what each does and the tables it reads (from the workbook)."""
    return dict(json.loads((_DIR / "tool_catalog.json").read_text(encoding="utf-8")))


__all__ = ["GROUPS", "system_prompt", "table_group", "tool_catalog"]
