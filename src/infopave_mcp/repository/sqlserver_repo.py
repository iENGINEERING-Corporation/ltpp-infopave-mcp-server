"""SQL Server backend (placeholder).

The query methods are not ported yet: the DuckDB backend's SQL uses DuckDB features (ILIKE, FILTER, ASOF
JOIN, list_contains, median), and each query needs a T-SQL version before this backend can answer
questions. Until then every unported method raises NotImplementedError (see Repository), and only the
metadata methods below work. Needs the `sqlserver` extra (pyodbc) and an ODBC driver.
"""

from typing import Any

from infopave_mcp.repository.base import Repository, Row


class SqlServerRepository(Repository):
    name = "sqlserver"

    def __init__(self, connection_string: str | None):
        if not connection_string:
            raise ValueError("Set INFOPAVE_SQLSERVER_CONNECTION to an ODBC connection string.")
        self.connection_string = connection_string

    def _connect(self) -> Any:
        try:
            import pyodbc  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise RuntimeError("Install the 'sqlserver' extra: pip install infopave-mcp[sqlserver]") from exc
        return pyodbc.connect(self.connection_string)

    def _rows(self, sql: str, params: list[Any]) -> list[Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            columns = [c[0].lower() for c in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    def list_tables(self) -> list[str]:
        rows = self._rows(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA IN ('INFOPAVE', 'LTPPDBA', 'MERRA_TOOL') ORDER BY TABLE_NAME",
            [],
        )
        return [r["table_name"] for r in rows]

    def table_columns(self, table: str) -> list[Row]:
        if table.upper() not in self.list_tables():
            raise ValueError(f"Unknown table '{table}'.")
        return self._rows(
            "SELECT LOWER(COLUMN_NAME) AS column_name, DATA_TYPE AS column_type "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            [table.upper()],
        )
