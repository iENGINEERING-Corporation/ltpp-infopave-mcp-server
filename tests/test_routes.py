"""The template's HTTP-only routes (cloud platforms poll /health)."""

from starlette.testclient import TestClient

from infopave_mcp import __version__
from infopave_mcp.app import mcp


def test_health_and_version_routes():
    client = TestClient(mcp.http_app())
    assert client.get("/health").json() == {"status": "healthy", "service": "infopave-mcp"}
    assert client.get("/version").json() == {"version": __version__}
