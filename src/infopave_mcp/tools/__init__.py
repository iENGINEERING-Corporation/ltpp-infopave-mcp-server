"""One module per domain. Each defines its tools plus a register(mcp) function."""

from fastmcp import FastMCP

from infopave_mcp.tools import (
    climate,
    construction,
    cross_dataset,
    maintenance,
    materials,
    performance,
    sections,
    traffic,
)


def register_all(mcp: FastMCP) -> None:
    """Register every tool module. Add new modules here."""
    sections.register(mcp)
    materials.register(mcp)
    construction.register(mcp)
    performance.register(mcp)
    climate.register(mcp)
    traffic.register(mcp)
    maintenance.register(mcp)
    cross_dataset.register(mcp)
