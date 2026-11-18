"""HTTP-only routes (active when served over streamable HTTP, next to /mcp).

`/health` is what cloud.gov, IBM Code Engine and Databricks Apps poll to decide the app started.
Keep it fast and dependency-free (it must not touch the data pack).
"""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from infopave_mcp import __version__


def register_routes(mcp: FastMCP) -> None:
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": "infopave-mcp"})

    @mcp.custom_route("/version", methods=["GET"])
    async def version(request: Request) -> JSONResponse:
        return JSONResponse({"version": __version__})
