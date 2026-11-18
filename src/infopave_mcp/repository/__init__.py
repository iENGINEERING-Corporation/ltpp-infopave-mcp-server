from functools import lru_cache

from infopave_mcp.config import get_settings
from infopave_mcp.repository.base import FieldInfo, Repository, Row


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    """The configured backend (INFOPAVE_BACKEND), created once."""
    settings = get_settings()
    if settings.backend == "duckdb":
        from infopave_mcp.repository.duckdb_repo import DuckDBRepository

        return DuckDBRepository(settings.data_dir)
    if settings.backend == "sqlserver":
        from infopave_mcp.repository.sqlserver_repo import SqlServerRepository

        return SqlServerRepository(settings.sqlserver_connection)
    raise ValueError(f"Unknown INFOPAVE_BACKEND '{settings.backend}'. Use 'duckdb' or 'sqlserver'.")


__all__ = ["FieldInfo", "Repository", "Row", "get_repository"]
