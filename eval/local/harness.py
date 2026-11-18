"""Call the server over the real MCP protocol, in memory (no subprocess, no network).

Importing this module points the server at eval/local/sample_pack unless INFOPAVE_DATA_DIR is already
set, so tests and CI run without the 106 MB data pack. Set INFOPAVE_DATA_DIR to test the full pack.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

EVALS_DIR = Path(__file__).resolve().parent
SAMPLE_PACK = EVALS_DIR / "sample_pack"
os.environ.setdefault("INFOPAVE_DATA_DIR", str(SAMPLE_PACK))

from fastmcp import Client  # noqa: E402
from mcp import ClientSession  # noqa: E402

from infopave_mcp.app import create_server  # noqa: E402

logging.disable(logging.INFO)  # the SDK logs every request at INFO

T = TypeVar("T")


@dataclass
class ToolResult:
    name: str
    args: dict[str, Any]
    is_error: bool
    text: str
    envelope: dict[str, Any] | None  # parsed Envelope, or None on error

    @property
    def data(self) -> Any:
        assert self.envelope is not None, f"{self.name} failed: {self.text}"
        return self.envelope["data"]


@asynccontextmanager
async def open_session() -> AsyncIterator[ClientSession]:
    # fastmcp's in-memory transport; .session is the underlying MCP ClientSession.
    async with Client(create_server()) as client:
        yield client.session


async def call(client: ClientSession, name: str, args: dict[str, Any] | None = None) -> ToolResult:
    args = args or {}
    result = await client.call_tool(name, args)
    text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
    envelope = None
    if not result.is_error:
        envelope = result.structured_content or json.loads(text)
    return ToolResult(name, args, bool(result.is_error), text, envelope)


def run(fn: Callable[[ClientSession], Awaitable[T]]) -> T:
    """Run an async function against a fresh in-memory server session."""

    async def main() -> T:
        async with open_session() as client:
            return await fn(client)

    return asyncio.run(main())


def call_tool(name: str, args: dict[str, Any] | None = None) -> ToolResult:
    return run(lambda c: call(c, name, args))


def pack_is_sample() -> bool:
    """True if the data pack in use is the small sample (full-pack facts do not apply)."""
    folder = Path(os.environ["INFOPAVE_DATA_DIR"])
    try:
        return bool(json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("sample", False))
    except (OSError, ValueError):  # no manifest: it is the sample only if it is the committed one
        return folder.resolve() == SAMPLE_PACK.resolve()
