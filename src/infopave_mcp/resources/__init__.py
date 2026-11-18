"""infopave:// resources: reference material the user or client can attach as context."""

import json
from typing import Any

from fastmcp import FastMCP

from infopave_mcp import kb
from infopave_mcp.repository import get_repository
from infopave_mcp.services import topics
from infopave_mcp.services.sections import resolve_section
from infopave_mcp.services.topics import scrub


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def register(mcp: FastMCP) -> None:
    @mcp.resource("infopave://system-prompt", mime_type="text/markdown")
    def system_prompt() -> str:
        """How the AI should use this server: workflow, envelope, reading the data."""
        return kb.system_prompt()

    @mcp.resource("infopave://tools", mime_type="application/json")
    def tools() -> str:
        """The tool catalogue: every tool by group and what it does."""
        catalogue = kb.tool_catalog()
        return _json({"tools": [{k: v for k, v in t.items() if k != "source_tables"} for t in catalogue["tools"]]})

    @mcp.resource("infopave://release", mime_type="application/json")
    def release() -> str:
        """The LTPP Standard Data Release the pack comes from, and the pack manifest if there is one."""
        repo = get_repository()
        data: dict[str, Any] = {"data_release": repo.data_release()}
        omitted = {topics.public_title(t): cols for t, cols in repo.omitted_columns().items()}
        if omitted:
            data["columns_not_served"] = omitted
            data["columns_not_served_reason"] = "A value is not valid UTF-8 in the data pack, so DuckDB cannot read it."
        try:
            manifest = repo.manifest()  # the per-table list is internal: only the pack-level facts are shown
            data["manifest"] = {k: manifest[k] for k in ("data_release", "built_at", "sample", "note") if k in manifest}
        except FileNotFoundError:
            data["manifest"] = None
        return _json(data)

    @mcp.resource("infopave://topics", mime_type="application/json")
    def topic_list() -> str:
        """Every data topic: key, group, title and what it holds."""
        repo = get_repository()
        sizes = {r["table"]: int(r["rows"]) for r in repo.table_sizes()}
        described = {r["table_name"]: r for r in repo.table_catalog()}
        out = [
            {
                "topic": t.key,
                "group": kb.table_group(t.table),
                "title": t.title,
                "records": sizes.get(t.table),
                "description": (described.get(t.table) or {}).get("description"),
            }
            for t in topics.TOPICS
        ]
        return _json(scrub(out))

    @mcp.resource("infopave://topic/{topic}", mime_type="application/json")
    def topic_columns(topic: str) -> str:
        """Columns of one topic with type, units, code type and meaning, e.g. infopave://topic/roughness."""
        repo = get_repository()
        tp = topics.topic(topic)
        info = repo.field_info(tp.table)
        columns = []
        for c in repo.table_columns(tp.table):
            fi = info.get(c["column_name"])
            columns.append(
                {
                    "column": c["column_name"],
                    "type": c["column_type"],
                    "units": fi.units if fi else None,
                    "code_type": fi.code_type if fi else None,
                    "description": fi.description if fi else None,
                }
            )
        return _json(scrub({"topic": tp.key, "title": tp.title, "group": kb.table_group(tp.table), "columns": columns}))

    @mcp.resource("infopave://codes/{code_type}", mime_type="application/json")
    def codes(code_type: str) -> str:
        """What each code of one code type means, e.g. infopave://codes/MAINT_WORK or infopave://codes/PAVEMENT_FAMILY."""
        labels = get_repository().code_labels(code_type)
        if not labels:
            raise ValueError(f"No codes for '{code_type}'. Code types are named in the topic resource (code_type).")
        return _json({"code_type": code_type.upper(), "codes": labels})

    @mcp.resource("infopave://section/{state}/{shrp_id}", mime_type="application/json")
    def section(state: str, shrp_id: str) -> str:
        """General record of one test section, e.g. infopave://section/Ohio/0207."""
        ref = resolve_section(get_repository(), state, shrp_id)
        return _json({"section": ref.key(), "record": {k: v for k, v in ref.record.items() if v is not None}})
