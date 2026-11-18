"""MCP server entry point: builds the FastMCP app and picks the transport.

Kept thin, as in the hackathon template. The logic lives in the submodules:
  tools/ (one module per domain), resources/, prompts/, routes.py (HTTP-only /health, /version),
  services/ (units, field metadata, section resolution, caveats ...), repository/ (data access),
  models/ (Pydantic inputs and the response Envelope), kb/ (system prompt, tool catalogue).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from fastmcp import FastMCP

from infopave_mcp import kb, prompts, resources, routes, tools
from infopave_mcp.config import get_settings


def create_server() -> FastMCP:
    """Build the server with all tools, resources, prompts and routes registered."""
    mcp = FastMCP(name="infopave", instructions=kb.system_prompt())
    tools.register_all(mcp)
    resources.register(mcp)
    prompts.register(mcp)
    routes.register_routes(mcp)
    return mcp


# Module-level instance so `fastmcp run`, the IBM toolkit entrypoint and tests can import `mcp`.
mcp = create_server()


def main(argv: Sequence[str] | None = None) -> None:
    """Start the server.

    Transport precedence:
      1. A platform-injected port (`DATABRICKS_APP_PORT` or `PORT`) -> HTTP on 0.0.0.0:<port>.
      2. `--transport http` / INFOPAVE_TRANSPORT=http -> HTTP on --host/--port (default 127.0.0.1:8000).
      3. Otherwise stdio, which is how Claude Desktop / Claude Code launch the server.
    """
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="infopave-mcp", description="InfoPave MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http"],
        default=settings.transport,
        help="stdio for desktop clients (default); http serves streamable HTTP at /mcp",
    )
    parser.add_argument("--host", default=settings.host, help="HTTP bind address")
    parser.add_argument("--port", type=int, default=settings.port, help="HTTP port")
    parser.add_argument("--data-dir", help="Data pack folder (sets INFOPAVE_DATA_DIR)")
    args = parser.parse_args(argv)

    if args.data_dir:  # must be set before the repository first reads settings
        os.environ["INFOPAVE_DATA_DIR"] = args.data_dir
        get_settings.cache_clear()

    platform_port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if platform_port:
        mcp.run(transport="http", host="0.0.0.0", port=int(platform_port))
    elif args.transport in ("http", "streamable-http"):
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        # stdio: stdout carries the protocol, so nothing in this program may print() to it.
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
