"""DuckDB backend: every data-pack Parquet file becomes a view named after its table.

Files are named SCHEMA.TABLE.parquet (INFOPAVE.LDW_DP_GENERAL.parquet), and the view is just TABLE, so
the names match the LTPP documentation and the tool catalogue.
"""

import difflib
import json
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from infopave_mcp.models.inputs import DateRange, Page, SectionFilter, SectionGroup
from infopave_mcp.models.query import Aggregate, Cond, MeasureSpec, Select
from infopave_mcp.repository.base import FieldInfo, Repository, Row

SECTIONS = "LDW_DP_GENERAL"

# Columns the data pack holds but DuckDB cannot read, because a value is not valid UTF-8
# (ANALYSIS_DIS_CRCP.OTHER has a Latin-1 superscript two: "PUNCHOUT AREA = 36.6M²"). They are left out of
# the table's view. Fix at the source by re-exporting the text as UTF-8; remove the entry once it is fixed.
UNREADABLE_COLUMNS: dict[str, tuple[str, ...]] = {"ANALYSIS_DIS_CRCP": ("OTHER",)}

# group_by name -> (select expressions, result column names). Used by group_sections.
SECTION_GROUPS: dict[str, list[tuple[str, str]]] = {
    "state": [('g."STATE_NAME"', "state"), ('g."STATE_CODE"', "state_code")],
    "region": [('g."REGION_DES"', "region")],
    "climate_zone": [('g."CLIMATIC_REGION_DETAIL"', "climate_zone")],
    "experiment_type": [('g."EXPERIMENT_TYPE_DETAIL"', "experiment_type")],
    "sps_project": [("coalesce(g.\"ALL_SECTION_EXPIREMENT\", '(GPS)')", "sps_project")],
    "gps_sps": [("CASE g.\"GPS_SPS\" WHEN 'G' THEN 'GPS' WHEN 'S' THEN 'SPS' END", "gps_sps")],
    "top_layer": [
        (
            "CASE g.\"TOP_LAYER_TYPE_CODE\" WHEN 'AC' THEN 'Asphalt concrete' "
            "WHEN 'PC' THEN 'Portland cement concrete' END",
            "top_layer",
        ),
    ],  # fmt: skip
    "functional_class": [('g."FUNC_CLASS_DETAIL"', "functional_class")],
    "monitoring_status": [('g."LTPP_MONITORING_STATUS_DET"', "monitoring_status")],
    "construction_decade": [
        ('CAST(floor(year(g."DATE_OF_CONSTRUCTION") / 10) * 10 AS INTEGER)', "construction_decade"),
    ],  # fmt: skip
    "county": [('g."STATE_NAME"', "state"), ('g."COUNTY_NAME"', "county")],
    "lanes": [('g."NO_OF_LANES"', "lanes")],
}


# Total thickness of asphalt layers (AC + AC-treated) per section and construction event, in inches.
_AC_EVENTS_CTE = """ac_events AS (
    SELECT sc, sid, cn, sum(t) AS t FROM (
        SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid, "CONSTRUCTION_NO" AS cn, "REPR_THICKNESS" AS t FROM "ANALYSIS_TST_AC"
        UNION ALL
        SELECT "STATE_CODE", "SHRP_ID", "CONSTRUCTION_NO", "REPR_THICKNESS" FROM "ANALYSIS_TST_ACT"
    ) WHERE t IS NOT NULL GROUP BY 1, 2, 3
)"""
# ... and for each section the value in its most recent construction event that has asphalt layers.
_AC_LATEST_CTE = "ac_latest AS (SELECT sc, sid, arg_max(t, cn) AS ac_in FROM ac_events GROUP BY 1, 2)"

_PAVEMENT_CLASS_CASE = (
    "CASE WHEN o.fam IN ('ACUB','ACATB','ACCTB','ACTB') THEN 'flexible' "
    "WHEN o.fam = 'ACPCC' THEN 'composite' "
    "WHEN o.fam IN ('JPCTB','JPCUB','JRCTB','JRCUB','CRCTB','CRCUB','PCPCC') THEN 'rigid' ELSE 'other' END"
)


def _json_safe(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.date() if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) else v
    return v


def distance_km_sql(alias: str) -> str:
    """Great-circle km from alias.LATITUDE/LONGITUDE to a point; takes 3 ? params: lat, lat, lon."""
    return f"""
        6371 * 2 * asin(sqrt(
            pow(sin(radians({alias}."LATITUDE" - ?) / 2), 2)
            + cos(radians(?)) * cos(radians({alias}."LATITUDE"))
              * pow(sin(radians({alias}."LONGITUDE" - ?) / 2), 2)
        ))
    """


def section_where(f: SectionFilter, alias: str = "g") -> tuple[list[str], list[Any]]:
    """WHERE conditions and params for LDW_DP_GENERAL columns, under the given table alias."""
    a = alias
    where: list[str] = []
    params: list[Any] = []
    if f.state_codes:
        where.append(f'list_contains(?, {a}."STATE_CODE")')
        params.append(f.state_codes)
    if f.region:
        where.append(f'{a}."REGION_DES" = ?')
        params.append(f.region)
    if f.climate_zone:
        where.append(f"replace(replace(lower({a}.\"CLIMATIC_REGION_DETAIL\"), ', ', '-'), ' ', '-') = ?")
        params.append(f.climate_zone)
    if f.experiment:
        where.append(
            f'({a}."EXPERIMENT_TYPE_DETAIL" ILIKE ? OR {a}."CURRENT_EXPERIMENT_TYPE" = ? '
            f'OR {a}."ALL_SECTION_EXPIREMENT" ILIKE ?)'
        )
        params += [f"%{f.experiment}%", f.experiment.upper(), f.experiment]
    if f.gps_sps:
        where.append(f'{a}."GPS_SPS" = ?')
        params.append("G" if f.gps_sps == "GPS" else "S")
    if f.top_layer:
        where.append(f'{a}."TOP_LAYER_TYPE_CODE" = ?')
        params.append("AC" if f.top_layer == "AC" else "PC")
    if f.functional_class:
        where.append(f'{a}."FUNC_CLASS_DETAIL" ILIKE ?')
        params.append(f"%{f.functional_class}%")
    if f.monitoring_status == "active":
        where.append(f'{a}."LTPP_MONITORING_STATUS" IS NULL')
    elif f.monitoring_status == "out-of-study":
        where.append(f"{a}.\"LTPP_MONITORING_STATUS\" = 'O'")
    if f.county:
        where.append(f'{a}."COUNTY_NAME" ILIKE ?')
        params.append(f"%{f.county}%")
    if f.constructed_after is not None:
        where.append(f'year({a}."DATE_OF_CONSTRUCTION") >= ?')
        params.append(f.constructed_after)
    if f.constructed_before is not None:
        where.append(f'year({a}."DATE_OF_CONSTRUCTION") <= ?')
        params.append(f.constructed_before)
    if f.has_near:
        where.append(f"{distance_km_sql(a)} <= ?")
        params += [f.near_latitude, f.near_latitude, f.near_longitude, f.radius_km]
    return where, params


def where_sql(where: list[str]) -> str:
    return "WHERE " + " AND ".join(where) if where else ""


_NUMERIC_PREFIXES = (
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
    "DOUBLE", "FLOAT", "REAL", "DECIMAL",
)  # fmt: skip
RANK_STATS = ("max", "min", "avg", "sum", "median", "count")
# Columns that identify a record; shown beside the value when individual records are ranked.
RECORD_ID_COLUMNS = ("STATE_CODE", "SHRP_ID", "CONSTRUCTION_NO", "LAYER_NO", "MERRA_ID", "YEAR", "MONTH")


def is_numeric_type(sql_type: str) -> bool:
    return sql_type.upper().startswith(_NUMERIC_PREFIXES)


def is_date_type(sql_type: str) -> bool:
    return sql_type.upper().startswith(("DATE", "TIMESTAMP"))


def _round(v: Any, digits: int = 4) -> Any:
    return round(v, digits) if isinstance(v, float) else v


class DuckDBRepository(Repository):
    name = "duckdb"

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()
        self._tables: dict[str, str] = {}  # TABLE -> SCHEMA
        self._omitted: dict[str, list[str]] = {}  # TABLE -> columns left out of its view
        self._columns: dict[str, dict[str, str]] = {}
        self._fields: dict[str, dict[str, FieldInfo]] = {}
        self._codes: dict[str, dict[str, str]] = {}
        self._release: Row | None = None

    # --- plumbing -----------------------------------------------------------------------------
    def _connection(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                files = sorted(self.data_dir.glob("*.parquet"))
                if not files:
                    raise FileNotFoundError(
                        f"No .parquet files in {self.data_dir}. Set INFOPAVE_DATA_DIR to the data pack."
                    )
                conn = duckdb.connect()
                for f in files:
                    schema, _, table = f.stem.rpartition(".")
                    self._tables[table.upper()] = schema
                    present = {
                        r[0].upper()
                        for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{f.as_posix()}')").fetchall()
                    }  # schema only: no data is read, so an unreadable value cannot raise here
                    skip = tuple(c for c in UNREADABLE_COLUMNS.get(table.upper(), ()) if c in present)
                    if skip:
                        self._omitted[table.upper()] = list(skip)
                    exclude = f" EXCLUDE ({', '.join(chr(34) + c + chr(34) for c in skip)})" if skip else ""
                    conn.execute(
                        f"CREATE VIEW \"{table.upper()}\" AS SELECT *{exclude} FROM read_parquet('{f.as_posix()}')"
                    )
                self._conn = conn
        return self._conn

    def query(self, sql: str, params: list[Any] | None = None) -> list[Row]:
        cur = self._connection().cursor()  # one cursor per call keeps concurrent calls safe
        result = cur.execute(sql, params or [])
        columns = [d[0].lower() for d in result.description]
        return [dict(zip(columns, map(_json_safe, row), strict=True)) for row in result.fetchall()]

    def _one(self, sql: str, params: list[Any] | None = None) -> Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def omitted_columns(self) -> dict[str, list[str]]:
        """Columns present in the data pack but left out because they cannot be read (see UNREADABLE_COLUMNS)."""
        self._connection()
        return {t: list(cols) for t, cols in self._omitted.items()}

    def has_table(self, table: str) -> bool:
        self._connection()
        return table.upper() in self._tables

    def _table(self, table: str) -> str:
        self._connection()
        name = table.upper()
        if name not in self._tables:
            raise ValueError("Unknown dataset.")
        return name

    def schema_of(self, table: str) -> dict[str, str]:
        """{COLUMN: type} for a table (upper-case column names)."""
        name = self._table(table)
        if name not in self._columns:
            rows = self._connection().execute(f'DESCRIBE "{name}"').fetchall()
            self._columns[name] = {r[0].upper(): r[1] for r in rows}
        return self._columns[name]

    def _column(self, table: str, column: str) -> str:
        col = column.upper()
        schema = self.schema_of(table)
        if col not in schema:
            close = difflib.get_close_matches(col, list(schema), n=4, cutoff=0.5)
            hint = f" Did you mean {', '.join(c.lower() for c in close)}?" if close else ""
            raise ValueError(f"No column '{column}' in this dataset.{hint} (get_data_overview lists the columns.)")
        return col

    def _conditions(self, table: str, conds: list[Cond]) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        for c in conds:
            col = f'"{self._column(table, c.column)}"'
            if c.op == "isnull" or (c.op == "eq" and c.value is None):
                where.append(f"{col} IS NULL")
            elif c.op == "notnull" or (c.op == "ne" and c.value is None):
                where.append(f"{col} IS NOT NULL")
            elif c.op == "in":
                where.append(f"list_contains(?, {col})")
                params.append(list(c.value))
            elif c.op == "like":
                where.append(f"{col} ILIKE ?")
                params.append(f"%{c.value}%")
            else:
                sql_op = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[c.op]
                where.append(f"{col} {sql_op} ?")
                params.append(c.value)
        return where, params

    # --- Generic access ------------------------------------------------------------------------
    def select(self, sel: Select) -> tuple[list[Row], int]:
        table = self._table(sel.table)
        cols = [self._column(table, c) for c in sel.columns] if sel.columns else list(self.schema_of(table))
        select_list = ", ".join(f'"{c}" AS "{c.lower()}"' for c in cols)
        where, params = self._conditions(table, sel.where)
        order = ", ".join(f'"{self._column(table, c)}" {"DESC" if d else "ASC"} NULLS LAST' for c, d in sel.order_by)
        distinct = "DISTINCT " if sel.distinct else ""
        base = f'FROM "{table}" {where_sql(where)}'
        tail = f" ORDER BY {order}" if order else ""
        if sel.limit is None:
            rows = self.query(f"SELECT {distinct}{select_list} {base}{tail}", params)
            return rows, len(rows)
        paged = f"{tail} LIMIT {int(sel.limit)} OFFSET {int(sel.offset)}"
        if sel.distinct:
            total = self.query(f"SELECT count(*) AS n FROM (SELECT DISTINCT {select_list} {base})", params)[0]["n"]
            return self.query(f"SELECT DISTINCT {select_list} {base}{paged}", params), total
        rows = self.query(f"SELECT {select_list}, count(*) OVER () AS _total {base}{paged}", params)
        if rows:
            total = rows[0]["_total"]
        elif sel.offset > 0:
            total = self.count(table, sel.where)
        else:
            total = 0
        for r in rows:
            del r["_total"]
        return rows, total

    def aggregate(self, agg: Aggregate) -> tuple[list[Row], int]:
        table = self._table(agg.table)
        groups = [self._column(table, c) for c in agg.group_by]
        parts = [f'"{c}" AS "{c.lower()}"' for c in groups] + ["count(*) AS n_rows"]
        d = int(agg.digits)
        for c in (self._column(table, x) for x in agg.avg):
            parts.append(f'round(avg("{c}"), {d}) AS "{c.lower()}"')
        for c in (self._column(table, x) for x in agg.minmax):
            parts.append(f'min("{c}") AS "{c.lower()}_min"')
            parts.append(f'max("{c}") AS "{c.lower()}_max"')
        for c in (self._column(table, x) for x in agg.flags):
            parts.append(f'list_sort(list(DISTINCT "{c}") FILTER (WHERE "{c}" IS NOT NULL)) AS "{c.lower()}"')
        where, params = self._conditions(table, agg.where)
        by = ", ".join(f'"{c}"' for c in groups)
        order = (
            ", ".join(f'"{self._column(table, c)}" {"DESC" if desc else "ASC"} NULLS LAST' for c, desc in agg.order_by)
            or by
        )
        sql = f"""SELECT {", ".join(parts)}, count(*) OVER () AS _total
                  FROM "{table}" {where_sql(where)} GROUP BY {by} ORDER BY {order}"""
        # count(*) OVER () after GROUP BY counts groups; apply paging on top
        inner = f"SELECT * FROM ({sql}) q"
        if agg.limit is not None:
            inner += f" LIMIT {int(agg.limit)} OFFSET {int(agg.offset)}"
        rows = self.query(inner, params)
        total = rows[0]["_total"] if rows else 0
        if not rows and agg.offset > 0:
            total = self.query(
                f'SELECT count(*) AS n FROM (SELECT 1 FROM "{table}" {where_sql(where)} GROUP BY {by})',
                params,
            )[0]["n"]
        for r in rows:
            del r["_total"]
        return rows, int(total)

    def count(self, table: str, where: list[Cond]) -> int:
        name = self._table(table)
        conds, params = self._conditions(name, where)
        return int(self.query(f'SELECT count(*) AS n FROM "{name}" {where_sql(conds)}', params)[0]["n"])

    def section_tables(self) -> list[str]:
        self._connection()
        keyed = [
            t for t in sorted(self._tables)
            if t != SECTIONS and {"STATE_CODE", "SHRP_ID"} <= set(self.schema_of(t))
        ]  # fmt: skip
        return keyed

    def dataset_counts(self, state_code: int, shrp_id: str, tables: list[str]) -> dict[str, int]:
        names = [self._table(t) for t in tables]
        for n in names:
            schema = self.schema_of(n)
            if "STATE_CODE" not in schema or "SHRP_ID" not in schema:
                raise ValueError(f"Table {n} is not keyed by section.")
        sql = " UNION ALL ".join(
            f'SELECT \'{n}\' AS t, count(*) AS n FROM "{n}" WHERE "STATE_CODE" = ? AND "SHRP_ID" = ?' for n in names
        )
        params: list[Any] = []
        for _ in names:
            params += [state_code, shrp_id]
        return {r["t"]: int(r["n"]) for r in self.query(sql, params)}

    # --- Dataset-wide summaries ----------------------------------------------------------------
    def _is_keyed(self, table: str) -> bool:
        return {"STATE_CODE", "SHRP_ID"} <= set(self.schema_of(table))

    def _date_column(self, table: str) -> str | None:
        """The table's main date column: one with DATE in its name, else the first date-typed column."""
        dates = [c for c, t in self.schema_of(table).items() if is_date_type(t)]
        return next((c for c in dates if "DATE" in c), dates[0] if dates else None)

    def table_sizes(self) -> list[Row]:
        self._connection()
        sql = " UNION ALL ".join(
            f'SELECT \'{t}\' AS "table", count(*) AS "rows" FROM "{t}"' for t in sorted(self._tables)
        )
        return self.query(sql)

    # --- Data pack metadata -------------------------------------------------------------------
    def list_tables(self) -> list[str]:
        self._connection()
        return sorted(self._tables)

    def has_column(self, table: str, column: str) -> bool:
        return column.upper() in self.schema_of(table)

    def table_columns(self, table: str) -> list[Row]:
        return [{"column_name": c.lower(), "column_type": t} for c, t in self.schema_of(table).items()]

    def manifest(self) -> Row:
        path = self.data_dir / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"No manifest.json in {self.data_dir}. Run data_pack/build.py manifest.")
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def data_release(self) -> Row:
        if self._release is None:
            row = self._one(
                """SELECT "STANDARD_DATA_RELEASE_ID" AS id, "STANDARD_DATA_RELEASE_NAME" AS name,
                          "STANDARD_DATA_RELEASE_YEAR" AS released
                   FROM "LDW_STANDARD_DATA_RELEASE" ORDER BY "STANDARD_DATA_RELEASE_ID" DESC LIMIT 1"""
            )
            if row is None:
                row = {"id": None, "name": "unknown release", "released": None}
            label = f"{row['name']} ({row['released']})" if row["released"] else str(row["name"])
            self._release = {**row, "label": label}
        return self._release

    def table_catalog(self) -> list[Row]:
        self._connection()
        return self.query(
            """SELECT "TABLE_NAME" AS table_name, "TABLE_ALIAS" AS title, "MODULE_NAME" AS module,
                      "SCHEMA_NAME" AS schema_name, "DESCRIPTION" AS description
               FROM "LDW_PPDB_TD" WHERE list_contains(?, "TABLE_NAME") ORDER BY "TABLE_NAME" """,
            [sorted(self._tables)],
        )

    def field_info(self, table: str) -> dict[str, FieldInfo]:
        name = self._table(table)
        if name not in self._fields:
            rows = self.query(
                """SELECT "FIELD_NAME" AS name, "DATA_TYPE" AS data_type, "UNITS" AS units,
                          "CODE_TYPE" AS code_type, "DESCRIPTION" AS description
                   FROM "LDW_PPDB_DD" WHERE "TABLE_NAME" = ? ORDER BY "FIELD_ORDER" """,
                [name],
            )
            self._fields[name] = {
                r["name"].lower(): FieldInfo(
                    name=r["name"].lower(),
                    data_type=r["data_type"],
                    units=r["units"],
                    code_type=r["code_type"],
                    description=r["description"],
                )
                for r in rows
            }
        return self._fields[name]

    def code_labels(self, code_type: str) -> dict[str, str]:
        key = code_type.upper()
        if key not in self._codes:
            rows = self.query('SELECT "CODE" AS code, "DETAIL" AS detail FROM "CODES" WHERE "CODETYPE" = ?', [key])
            labels: dict[str, str] = {}
            for r in rows:
                labels.setdefault(str(r["code"]), str(r["detail"]))  # first wins for repeated codes
            self._codes[key] = labels
        return self._codes[key]

    def code_types(self) -> list[Row]:
        return self.query("""SELECT "CODETYPE" AS code_type, "TITLE" AS title FROM "CODETYPES" ORDER BY "CODETYPE" """)

    # --- Sections ------------------------------------------------------------------------------
    def find_section(self, state_code: int, shrp_id: str) -> Row | None:
        return self._one(f'SELECT * FROM "{SECTIONS}" WHERE "STATE_CODE" = ? AND "SHRP_ID" = ?', [state_code, shrp_id])

    def similar_section_ids(self, state_code: int, shrp_id: str) -> list[str]:
        rows = self.query(
            f"""SELECT "SHRP_ID" AS shrp_id FROM "{SECTIONS}" WHERE "STATE_CODE" = ?
                ORDER BY jaro_winkler_similarity("SHRP_ID", ?) DESC, "SHRP_ID" LIMIT 5""",
            [state_code, shrp_id],
        )
        return [r["shrp_id"] for r in rows]

    def search_sections(self, f: SectionFilter, page: Page) -> tuple[list[Row], int]:
        where, params = section_where(f, "g")
        lead: list[Any] = []
        distance = ""
        order = '"state_code", "shrp_id"'
        if f.has_near:
            distance = f", round({distance_km_sql('g')}, 2) AS distance_km"
            lead = [f.near_latitude, f.near_latitude, f.near_longitude]
            order = "distance_km, " + order
        inner = f"""
            SELECT g."STATE_CODE" AS state_code, g."STATE_NAME" AS state, g."SHRP_ID" AS shrp_id,
                   g."LDW_SECTION_ID" AS ldw_section_id, g."COUNTY_NAME" AS county, g."ROUTE_DETAIL" AS route_type,
                   g."ROUTE_NO" AS route_no, g."DIRECTION_DETAIL" AS direction, g."FUNC_CLASS_DETAIL" AS functional_class,
                   g."REGION_DES" AS region, g."CLIMATIC_REGION_DETAIL" AS climate_zone,
                   g."EXPERIMENT_TYPE_DETAIL" AS experiment_type, g."ALL_SECTION_EXPIREMENT" AS sps_project,
                   CASE g."GPS_SPS" WHEN 'G' THEN 'GPS' WHEN 'S' THEN 'SPS' END AS gps_sps,
                   g."TOP_LAYER_TYPE_CODE" AS top_layer, g."LTPP_MONITORING_STATUS_DET" AS monitoring_status,
                   g."DATE_OF_CONSTRUCTION" AS date_of_construction, g."LATITUDE" AS latitude,
                   g."LONGITUDE" AS longitude {distance}
            FROM "{SECTIONS}" g {where_sql(where)}
        """
        sql = f"""SELECT *, count(*) OVER () AS _total FROM ({inner}) q
                  ORDER BY {order}
                  LIMIT {page.limit} OFFSET {page.offset}"""
        rows = self.query(sql, lead + params)
        if rows:
            total = rows[0]["_total"]
        elif page.offset > 0:
            total = self.query(f'SELECT count(*) AS n FROM "{SECTIONS}" g {where_sql(where)}', params)[0]["n"]
        else:
            total = 0
        for r in rows:
            del r["_total"]
        return rows, total

    def group_sections(self, group_by: str, f: SectionFilter, page: Page) -> tuple[list[Row], int, Row]:
        if group_by not in SECTION_GROUPS:
            raise ValueError(f"Unknown group_by '{group_by}'.")
        exprs = SECTION_GROUPS[group_by]
        where, params = section_where(f, "g")
        select_keys = ", ".join(f'{e} AS "{n}"' for e, n in exprs)
        names = [n for _, n in exprs]
        order = "construction_decade" if group_by == "construction_decade" else "sections DESC"
        rows = self.query(
            f"""
            WITH g1 AS (
                SELECT {select_keys},
                       count(*) AS sections,
                       count(*) FILTER (WHERE g."LTPP_MONITORING_STATUS" IS NULL) AS active,
                       count(*) FILTER (WHERE g."LTPP_MONITORING_STATUS" = 'O') AS out_of_study,
                       min(year(g."DATE_OF_CONSTRUCTION")) AS earliest_construction,
                       max(year(g."DATE_OF_CONSTRUCTION")) AS latest_construction
                FROM "{SECTIONS}" g {where_sql(where)}
                GROUP BY {", ".join(f'"{n}"' for n in names)}
            )
            SELECT *, round(100.0 * sections / sum(sections) OVER (), 1) AS pct_of_sections,
                   count(*) OVER () AS _groups, sum(sections) OVER () AS _sections
            FROM g1 ORDER BY {order}, {", ".join(f'"{n}"' for n in names)}
            LIMIT {page.limit} OFFSET {page.offset}
            """,
            params,
        )
        if not rows:
            return [], 0, {"sections": 0}
        totals = {"sections": int(rows[0]["_sections"])}
        groups = int(rows[0]["_groups"])
        for r in rows:
            del r["_groups"], r["_sections"]
        return rows, groups, totals

    # --- Materials -----------------------------------------------------------------------------
    def material_group_stats(
        self,
        table: str,
        column: str,
        group_by: str,
        f: SectionFilter,
        layer_types: list[str] | None,
        page: Page,
    ) -> tuple[list[Row], int, Row]:
        name = self._table(table)
        col = self._column(name, column)
        if group_by == "layer_type":
            exprs = [('t."LAYER_TYPE"', "layer_type")]
        elif group_by in SECTION_GROUPS:
            exprs = SECTION_GROUPS[group_by]
        else:
            raise ValueError(f"Unknown group_by '{group_by}'.")
        where, params = section_where(f, "g")
        where.insert(0, f't."{col}" IS NOT NULL')
        if layer_types:
            where.append('list_contains(?, t."LAYER_TYPE")')
            params.append(layer_types)
        join = (
            f'FROM "{name}" t JOIN "{SECTIONS}" g '
            'ON g."STATE_CODE" = t."STATE_CODE" AND g."SHRP_ID" = t."SHRP_ID" '
            f"{where_sql(where)}"
        )
        stats = (
            "count(*) AS layers, count(DISTINCT (sc, sid)) AS sections, "
            "avg(v) AS mean, median(v) AS median, stddev_samp(v) AS std_dev, min(v) AS min, max(v) AS max, "
            "quantile_cont(v, 0.25) AS p25, quantile_cont(v, 0.75) AS p75"
        )
        names = [n for _, n in exprs]
        keys = ", ".join(f'{e} AS "{n}"' for e, n in exprs)
        order = names[0] if group_by == "construction_decade" else "layers DESC"
        # keys are computed first so a key named like a source column (state_code) cannot be ambiguous
        keyed = f'keyed AS (SELECT {keys}, t."{col}" AS v, t."STATE_CODE" AS sc, t."SHRP_ID" AS sid {join})'
        rows = self.query(
            f"""
            WITH {keyed}, g1 AS (SELECT {", ".join(f'"{n}"' for n in names)}, {stats} FROM keyed GROUP BY ALL)
            SELECT *, count(*) OVER () AS _groups FROM g1
            ORDER BY {order}, {", ".join(f'"{n}"' for n in names)}
            LIMIT {page.limit} OFFSET {page.offset}
            """,
            params,
        )
        overall = self.query(f"WITH {keyed} SELECT {stats} FROM keyed", params)[0]
        groups = int(rows[0]["_groups"]) if rows else 0
        for r in rows:
            del r["_groups"]
        return rows, groups, overall

    # --- Climate -------------------------------------------------------------------------------
    @staticmethod
    def _group_secs(grp: SectionFilter) -> tuple[str, list[Any]]:
        """CTE `grp_secs(sc, sid)`: the sections matching a group definition (and AC thickness bounds)."""
        where, params = section_where(grp, "g")
        ctes: list[str] = []
        join = ""
        ac_min = getattr(grp, "min_ac_thickness_in", None)
        ac_max = getattr(grp, "max_ac_thickness_in", None)
        if ac_min is not None or ac_max is not None:
            ctes += [_AC_EVENTS_CTE, _AC_LATEST_CTE]
            join = ' JOIN ac_latest a ON a.sc = g."STATE_CODE" AND a.sid = g."SHRP_ID"'
            if ac_min is not None:
                where.append("a.ac_in >= ?")
                params.append(ac_min)
            if ac_max is not None:
                where.append("a.ac_in <= ?")
                params.append(ac_max)
        ctes.append(
            f'grp_secs AS (SELECT g."STATE_CODE" AS sc, g."SHRP_ID" AS sid FROM "{SECTIONS}" g{join} {where_sql(where)})'
        )
        return ", ".join(ctes), params

    def climate_group_stats(
        self,
        table: str,
        column: str,
        group: SectionGroup,
        start_year: int | None,
        end_year: int | None,
        months: list[int] | None,
    ) -> Row:
        name = self._table(table)
        col = self._column(name, column)
        ctes, params = self._group_secs(group)
        where = [f't."{col}" IS NOT NULL']
        if start_year is not None:
            where.append('t."YEAR" >= ?')
            params.append(start_year)
        if end_year is not None:
            where.append('t."YEAR" <= ?')
            params.append(end_year)
        if months:
            where.append('list_contains(?, t."MONTH")')
            params.append(months)
        return self.query(
            f"""WITH {ctes},
                per_sec AS (
                    SELECT s.sc, s.sid, m."MERRA_ID" AS mid, avg(t."{col}") AS v
                    FROM grp_secs s
                    JOIN "MERRA_GRID_SECTION" m ON m."STATE_CODE" = s.sc AND m."SHRP_ID" = s.sid
                    JOIN "{name}" t ON t."MERRA_ID" = m."MERRA_ID"
                    {where_sql(where)}
                    GROUP BY 1, 2, 3
                )
                SELECT count(*) AS sections, count(DISTINCT mid) AS grid_cells,
                       round(avg(v), 4) AS mean, round(median(v), 4) AS median,
                       round(stddev_samp(v), 4) AS std_dev, round(min(v), 4) AS min, round(max(v), 4) AS max,
                       round(quantile_cont(v, 0.25), 4) AS p25, round(quantile_cont(v, 0.75), 4) AS p75
                FROM per_sec""",
            params,
        )[0]

    # --- Treatments ----------------------------------------------------------------------------
    _SUMMARY = "ANALYSIS_MNT_RHB_SUMMARY"
    _INTERVALS = {
        "profile": ("PRIOR_PROFILE_INTERVAL", "POST_PROFILE_INTERVAL"),
        "distress": ("PRIOR_DISTRESS_INTERVAL", "POST_DISTRESS_INTERVAL"),
        "deflection": ("PRIOR_DEFLECTION_INTERVAL", "POST_DEFLECTION_INTERVAL"),
    }

    def _treatment_cte(
        self,
        m: MeasureSpec,
        *,
        section: tuple[int, str] | None,
        group: SectionGroup | None,
        maint_codes: list[str] | None,
        surface_codes: list[str],
        exclude_flagged: bool,
        dates: DateRange | None,
    ) -> tuple[str, list[Any], bool]:
        """CTE chain ending in `pairs`: one row per treatment with the measurement before and after.

        Returns (sql, params in textual order, whether AC thickness bounds must be applied to `pairs`).
        """
        table = self._table(m.table)
        val, dat = self._column(table, m.value), self._column(table, m.date)
        prior_col, post_col = self._INTERVALS[m.interval]
        ctes: list[str] = []
        params: list[Any] = []

        ac_bounds = False
        join_group = ""
        if group is not None:
            sec_where, sec_params = section_where(group, "g")
            if sec_where:
                ctes.append(
                    f'grp_secs AS (SELECT g."STATE_CODE" AS sc, g."SHRP_ID" AS sid FROM "{SECTIONS}" g {where_sql(sec_where)})'
                )
                params += sec_params
                join_group = ' JOIN grp_secs gs ON gs.sc = s."STATE_CODE" AND gs.sid = s."SHRP_ID"'
            ac_bounds = group.min_ac_thickness_in is not None or group.max_ac_thickness_in is not None
        if ac_bounds:
            ctes.append(_AC_EVENTS_CTE)

        has_cn = self.has_column(table, "CONSTRUCTION_NO")
        obs_where = [f'"{val}" IS NOT NULL']
        if exclude_flagged:
            obs_where += [f'"{self._column(table, c)}" IS NULL' for c in m.flags if self.has_column(table, c)]
        if section is not None:
            obs_where.append('"STATE_CODE" = ? AND "SHRP_ID" = ?')
            params += [section[0], section[1]]
        cn_sel = '"CONSTRUCTION_NO" AS cn' if has_cn else "CAST(NULL AS BIGINT) AS cn"
        group_cols = "1, 2, 3, 4" if has_cn else "1, 2, 3"
        ctes.append(
            f'obs AS (SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid, "{dat}" AS d, {cn_sel}, avg("{val}") AS v '
            f'FROM "{table}" {where_sql(obs_where)} GROUP BY {group_cols})'
        )

        tx_where: list[str] = []
        if maint_codes:
            tx_where.append('list_contains(?, s."MAINT_WORK")')
            params.append(maint_codes)
        if group is not None and group.pavement_class:
            from infopave_mcp.models.inputs import PAVEMENT_CLASSES

            tx_where.append('list_contains(?, s."PRIOR_PAVEMENT_FAMILY")')
            params.append(list(PAVEMENT_CLASSES[group.pavement_class]))
        if section is not None:
            tx_where.append('s."STATE_CODE" = ? AND s."SHRP_ID" = ?')
            params += [section[0], section[1]]
        if dates is not None and dates.start_date:
            tx_where.append('s."IMP_DATE" >= ?')
            params.append(dates.start_date)
        if dates is not None and dates.end_date:
            tx_where.append('s."IMP_DATE" <= ?')
            params.append(dates.end_date)
        ctes.append(
            f'''tx AS (SELECT s."STATE_CODE" AS sc, s."SHRP_ID" AS sid, s."MAINT_WORK" AS mw, s."IMP_DATE" AS imp,
                      s."CONSTRUCTION_NO" AS tcn, s."{prior_col}" AS pi, s."{post_col}" AS qi,
                      s."PRIOR_PAVEMENT_FAMILY" AS pfam
                      FROM "{self._SUMMARY}" s{join_group} {where_sql(tx_where)})'''
        )
        ctes.append(
            """pairs AS (
                SELECT tx.*, p.d AS pd, p.v AS pv, p.cn AS pcn, a.d AS ad, a.v AS av, a.cn AS acn
                FROM tx
                ASOF LEFT JOIN obs p ON tx.sc = p.sc AND tx.sid = p.sid AND tx.imp >= p.d
                ASOF LEFT JOIN obs a ON tx.sc = a.sc AND tx.sid = a.sid AND tx.imp < a.d
            )"""
        )
        surface_list = ", ".join("?" for _ in surface_codes) or "NULL"
        params_status = list(surface_codes)
        ctes.append(
            f"""classified AS (
                SELECT pairs.*, (mw IN ({surface_list})) AS surface,
                  CASE WHEN pi IS NULL OR pd IS NULL OR pv IS NULL THEN 'no valid measurement before'
                       WHEN ad IS NULL OR av IS NULL THEN 'no measurement after'
                       WHEN mw IN ({surface_list}) THEN
                            CASE WHEN acn IS NOT NULL AND acn <> tcn
                                 THEN 'next measurement follows a later structural change' ELSE 'valid' END
                       WHEN qi IS NULL THEN 'no valid after-interval in the treatment record'
                       ELSE 'valid' END AS status
                FROM pairs
            )"""
        )
        params += params_status + params_status
        if ac_bounds:
            ctes.append(
                "pair_ac AS (SELECT c.*, e.t AS ac_in FROM classified c "
                "LEFT JOIN ac_events e ON e.sc = c.sc AND e.sid = c.sid AND e.cn = coalesce(c.pcn, c.tcn - 1))"
            )
        return ", ".join(ctes), params, ac_bounds

    def treatment_pairs(
        self,
        measure: MeasureSpec,
        *,
        state_code: int,
        shrp_id: str,
        maint_codes: list[str] | None,
        surface_codes: list[str],
        exclude_flagged: bool,
        dates: DateRange | None,
    ) -> list[Row]:
        cte, params, _ = self._treatment_cte(
            measure, section=(state_code, shrp_id), group=None, maint_codes=maint_codes,
            surface_codes=surface_codes, exclude_flagged=exclude_flagged, dates=dates,
        )  # fmt: skip
        return self.query(
            f"""WITH {cte}
                SELECT mw AS maint_work, imp AS imp_date, tcn AS construction_no, pfam AS prior_pavement_family,
                       surface, status, pd AS before_date, round(pv, 4) AS before_value,
                       ad AS after_date, round(av, 4) AS after_value, acn AS after_construction_no,
                       date_diff('month', pd, imp) AS months_before, date_diff('month', imp, ad) AS months_after
                FROM classified ORDER BY imp, mw""",
            params,
        )

    def treatment_effect(
        self,
        measure: MeasureSpec,
        group: SectionGroup,
        *,
        maint_codes: list[str] | None,
        surface_codes: list[str],
        exclude_flagged: bool,
        group_by: str | None,
        page: Page,
    ) -> tuple[list[Row], int, dict[str, int]]:
        cte, params, ac_bounds = self._treatment_cte(
            measure, section=None, group=group, maint_codes=maint_codes, surface_codes=surface_codes,
            exclude_flagged=exclude_flagged, dates=None,
        )  # fmt: skip
        src = "pair_ac" if ac_bounds else "classified"
        status_counts = {
            r["status"]: int(r["n"])
            for r in self.query(
                f"""WITH {cte}
                    SELECT status, count(*) AS n FROM {src}
                    {"WHERE " + " AND ".join(self._ac_pred(group)) if ac_bounds else ""} GROUP BY status""",
                params + (self._ac_params(group) if ac_bounds else []),
            )
        }
        where = ["status = 'valid'"] + (self._ac_pred(group) if ac_bounds else [])
        extra_params = self._ac_params(group) if ac_bounds else []
        if group_by is None:
            keys, join, names = "'all matching treatments' AS \"group\"", "", ["group"]
        elif group_by == "pavement_family":
            keys, join, names = 'pfam AS "pavement_family"', "", ["pavement_family"]
        elif group_by == "treatment":
            keys = 'mw AS "maint_work", coalesce(c.detail, mw) AS "treatment"'
            join = ' LEFT JOIN (SELECT "CODE" AS code, "DETAIL" AS detail FROM "CODES" WHERE "CODETYPE" = \'MAINT_WORK\') c ON c.code = v.mw'
            names = ["maint_work", "treatment"]
        elif group_by in SECTION_GROUPS:
            exprs = SECTION_GROUPS[group_by]
            keys = ", ".join(f'{e} AS "{n}"' for e, n in exprs)
            join = f' JOIN "{SECTIONS}" g ON g."STATE_CODE" = v.sc AND g."SHRP_ID" = v.sid'
            names = [n for _, n in exprs]
        else:
            raise ValueError(f"Unknown group_by '{group_by}'.")
        stats = """count(*) AS treatments, count(DISTINCT (sc, sid)) AS sections,
            round(avg(pv), 4) AS mean_before, round(avg(av), 4) AS mean_after,
            round(avg(av - pv), 4) AS mean_change, round(median(av - pv), 4) AS median_change,
            round(stddev_samp(av - pv), 4) AS std_dev_change,
            round(quantile_cont(av - pv, 0.25), 4) AS p25_change, round(quantile_cont(av - pv, 0.75), 4) AS p75_change,
            count(*) FILTER (WHERE av < pv) AS decreased, count(*) FILTER (WHERE av > pv) AS increased,
            round(avg(date_diff('month', pd, imp)), 1) AS mean_months_before,
            round(avg(date_diff('month', imp, ad)), 1) AS mean_months_after"""
        order = ", ".join(f'"{n}"' for n in names)
        # keys are computed first so a key named like a source column (state_code) cannot be ambiguous
        keyed = f"keyed AS (SELECT {keys}, v.pv, v.av, v.pd, v.ad, v.imp, v.sc, v.sid FROM v{join})"
        rows = self.query(
            f"""WITH {cte}, v AS (SELECT * FROM {src} WHERE {" AND ".join(where)}), {keyed},
                     grouped AS (SELECT {order}, {stats} FROM keyed GROUP BY ALL)
                SELECT *, count(*) OVER () AS _groups FROM grouped
                ORDER BY {"treatments DESC" if group_by in (None, "treatment") else order}, {order}
                LIMIT {page.limit} OFFSET {page.offset}""",
            params + extra_params,
        )
        groups = int(rows[0]["_groups"]) if rows else 0
        for r in rows:
            del r["_groups"]
        return rows, groups, status_counts

    @staticmethod
    def _ac_pred(group: SectionGroup) -> list[str]:
        preds = []
        if group.min_ac_thickness_in is not None:
            preds.append("ac_in >= ?")
        if group.max_ac_thickness_in is not None:
            preds.append("ac_in <= ?")
        return preds

    @staticmethod
    def _ac_params(group: SectionGroup) -> list[Any]:
        return [x for x in (group.min_ac_thickness_in, group.max_ac_thickness_in) if x is not None]

    # --- Cross-dataset finder ------------------------------------------------------------------
    def find_sections(self, criteria: dict[str, Any], f: SectionFilter, page: Page) -> tuple[list[Row], int]:
        c = criteria
        ctes: list[str] = []
        params: list[Any] = []
        select: list[str] = [
            'g."STATE_CODE" AS state_code', 'g."STATE_NAME" AS state', 'g."SHRP_ID" AS shrp_id',
            'g."COUNTY_NAME" AS county', 'g."CLIMATIC_REGION_DETAIL" AS climate_zone',
            'g."EXPERIMENT_TYPE_DETAIL" AS experiment_type', 'g."TOP_LAYER_TYPE_CODE" AS top_layer',
            'g."LATITUDE" AS latitude', 'g."LONGITUDE" AS longitude',
        ]  # fmt: skip
        joins: list[str] = []
        where, wparams = section_where(f, "g")

        def climate(alias: str, table: str, column: str) -> None:
            lo, hi = c.get(f"min_{alias}"), c.get(f"max_{alias}")
            if lo is None and hi is None and alias not in c.get("show", ()):
                return
            cw, cp = [f't."{column}" IS NOT NULL'], []
            if c.get("climate_start_year") is not None:
                cw.append('t."YEAR" >= ?')
                cp.append(c["climate_start_year"])
            if c.get("climate_end_year") is not None:
                cw.append('t."YEAR" <= ?')
                cp.append(c["climate_end_year"])
            ctes.append(
                f'''{alias}_cte AS (SELECT m."STATE_CODE" AS sc, m."SHRP_ID" AS sid, avg(t."{column}") AS v
                    FROM "MERRA_GRID_SECTION" m JOIN "{table}" t ON t."MERRA_ID" = m."MERRA_ID"
                    {where_sql(cw)} GROUP BY 1, 2)'''
            )
            params.extend(cp)
            joins.append(f'LEFT JOIN {alias}_cte {alias} ON {alias}.sc = g."STATE_CODE" AND {alias}.sid = g."SHRP_ID"')
            select.append(f"round({alias}.v, 2) AS {alias}")
            if lo is not None:
                where.append(f"{alias}.v >= ?")
                wparams.append(lo)
            if hi is not None:
                where.append(f"{alias}.v <= ?")
                wparams.append(hi)

        climate("mean_annual_precipitation_mm", "MERRA_PRECIP_YEAR", "PRECIPITATION")
        climate("mean_freeze_index", "MERRA_TEMP_YEAR", "FREEZE_INDEX")
        climate("mean_annual_air_temp_c", "MERRA_TEMP_YEAR", "TEMP_AVG")

        need_ac = any(c.get(k) is not None for k in ("min_ac_thickness_in", "max_ac_thickness_in"))
        if need_ac or "ac_thickness_in" in c.get("show", ()):
            ctes += [_AC_EVENTS_CTE, _AC_LATEST_CTE]
            joins.append('LEFT JOIN ac_latest ac ON ac.sc = g."STATE_CODE" AND ac.sid = g."SHRP_ID"')
            select.append("round(ac.ac_in, 2) AS ac_thickness_in")
            for key, op in (("min_ac_thickness_in", ">="), ("max_ac_thickness_in", "<=")):
                if c.get(key) is not None:
                    where.append(f"ac.ac_in {op} ?")
                    wparams.append(c[key])
        if c.get("min_pcc_thickness_in") is not None or c.get("max_pcc_thickness_in") is not None:
            ctes.append(
                """pcc_latest AS (SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid,
                       arg_max("REPR_THICKNESS", "CONSTRUCTION_NO") AS pcc_in
                   FROM "ANALYSIS_TST_PCC" WHERE "REPR_THICKNESS" IS NOT NULL GROUP BY 1, 2)"""
            )
            joins.append('LEFT JOIN pcc_latest pc ON pc.sc = g."STATE_CODE" AND pc.sid = g."SHRP_ID"')
            select.append("round(pc.pcc_in, 2) AS pcc_thickness_in")
            for key, op in (("min_pcc_thickness_in", ">="), ("max_pcc_thickness_in", "<=")):
                if c.get(key) is not None:
                    where.append(f"pc.pcc_in {op} ?")
                    wparams.append(c[key])
        if c.get("min_aadtt") is not None or c.get("max_aadtt") is not None:
            ctes.append(
                """aadtt_cte AS (SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid, max("REP_AADTT") AS aadtt
                   FROM "TRF_REP" WHERE "REP_AADTT" IS NOT NULL GROUP BY 1, 2)"""
            )
            joins.append('LEFT JOIN aadtt_cte tr ON tr.sc = g."STATE_CODE" AND tr.sid = g."SHRP_ID"')
            select.append("tr.aadtt AS representative_aadtt")
            for key, op in (("min_aadtt", ">="), ("max_aadtt", "<=")):
                if c.get(key) is not None:
                    where.append(f"tr.aadtt {op} ?")
                    wparams.append(c[key])
        if c.get("maint_codes"):
            tw, tp = ['list_contains(?, "MAINT_WORK")'], [c["maint_codes"]]
            if c.get("treated_after") is not None:
                tw.append('"IMP_DATE" >= ?')
                tp.append(c["treated_after"])
            if c.get("treated_before") is not None:
                tw.append('"IMP_DATE" <= ?')
                tp.append(c["treated_before"])
            ctes.append(
                f'''tx_cte AS (SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid, count(*) AS n, max("IMP_DATE") AS last_date
                    FROM "{self._SUMMARY}" {where_sql(tw)} GROUP BY 1, 2)'''
            )
            params.extend(tp)
            joins.append('JOIN tx_cte tx ON tx.sc = g."STATE_CODE" AND tx.sid = g."SHRP_ID"')
            select += ["tx.n AS matching_treatments", "tx.last_date AS last_matching_treatment"]
        for alias, table, val, dat, flag, lo_key, hi_key in (
            ("latest_mri", "ANALYSIS_IRI", "MRI", "VISIT_DATE", "MRI_FLAG", "min_latest_mri", "max_latest_mri"),
            ("latest_max_rut_mm", "ANALYSIS_RUTTING", "MAX_MEAN_DEPTH_1_8", "SURVEY_DATE", "MAX_MEAN_DEPTH_1_8_FLAG", "min_latest_rut_mm", "max_latest_rut_mm"),
        ):  # fmt: skip
            if c.get(lo_key) is None and c.get(hi_key) is None:
                continue
            ctes.append(
                f'''{alias}_cte AS (SELECT sc, sid, arg_max(v, d) AS v, max(d) AS d FROM (
                        SELECT "STATE_CODE" AS sc, "SHRP_ID" AS sid, "{dat}" AS d, avg("{val}") AS v
                        FROM "{table}" WHERE "{val}" IS NOT NULL AND "{flag}" IS NULL GROUP BY 1, 2, 3
                    ) GROUP BY 1, 2)'''
            )
            joins.append(f'LEFT JOIN {alias}_cte {alias} ON {alias}.sc = g."STATE_CODE" AND {alias}.sid = g."SHRP_ID"')
            select += [f"round({alias}.v, 3) AS {alias}", f"{alias}.d AS {alias}_date"]
            if c.get(lo_key) is not None:
                where.append(f"{alias}.v >= ?")
                wparams.append(c[lo_key])
            if c.get(hi_key) is not None:
                where.append(f"{alias}.v <= ?")
                wparams.append(c[hi_key])

        with_sql = f"WITH {', '.join(ctes)} " if ctes else ""
        sql = f"""{with_sql}SELECT {", ".join(select)}, count(*) OVER () AS _total
                  FROM "{SECTIONS}" g {" ".join(joins)} {where_sql(where)}
                  ORDER BY g."STATE_CODE", g."SHRP_ID" LIMIT {page.limit} OFFSET {page.offset}"""
        rows = self.query(sql, params + wparams)
        total = int(rows[0]["_total"]) if rows else 0
        if not rows and page.offset > 0:
            total = len(
                self.query(
                    f'{with_sql}SELECT 1 FROM "{SECTIONS}" g {" ".join(joins)} {where_sql(where)}',
                    params + wparams,
                )
            )
        for r in rows:
            del r["_total"]
        return rows, total

    # --- Performance ---------------------------------------------------------------------------
    def _measure_obs(self, m: MeasureSpec, families: list[str] | None, exclude_flagged: bool) -> tuple[str, list[Any]]:
        """CTE `obs`: one value per section and measurement date (runs and drops averaged)."""
        table = self._table(m.table)
        val, dat = self._column(table, m.value), self._column(table, m.date)
        where = [f't."{val}" IS NOT NULL']
        params: list[Any] = []
        if exclude_flagged:
            where += [f't."{self._column(table, c)}" IS NULL' for c in m.flags if self.has_column(table, c)]
        if families is not None:
            where.append('list_contains(?, t."PAVEMENT_FAMILY")')
            params.append(families)
        cte = f"""obs AS (
            SELECT t."STATE_CODE" AS sc, t."SHRP_ID" AS sid, t."{dat}" AS d,
                   t."PAVEMENT_FAMILY" AS fam, avg(t."{val}") AS v
            FROM "{table}" t {where_sql(where)} GROUP BY 1, 2, 3, 4
        )"""
        return cte, params

    def performance_groups(
        self,
        measure: MeasureSpec,
        group_by: str,
        f: SectionFilter,
        families: list[str] | None,
        age_bin_years: int,
        max_age_years: float | None,
        exclude_flagged: bool,
        page: Page,
    ) -> tuple[list[Row], int, Row]:
        if group_by == "pavement_family":
            exprs = [("o.fam", "pavement_family")]
        elif group_by == "pavement_class":
            exprs = [(_PAVEMENT_CLASS_CASE, "pavement_class")]
        elif group_by == "none":
            exprs = [("'all sections'", "group")]
        elif group_by in SECTION_GROUPS:
            exprs = SECTION_GROUPS[group_by]
        else:
            raise ValueError(f"Unknown group_by '{group_by}'.")
        cte, params = self._measure_obs(measure, families, exclude_flagged)
        sec_where, sec_params = section_where(f, "g")
        where = ["date_diff('day', g.\"DATE_OF_CONSTRUCTION\", o.d) >= 0", *sec_where]
        params = params + sec_params
        if max_age_years is not None:
            where.append("date_diff('day', g.\"DATE_OF_CONSTRUCTION\", o.d) / 365.25 <= ?")
            params.append(max_age_years)
        age = "date_diff('day', g.\"DATE_OF_CONSTRUCTION\", o.d) / 365.25"
        keys = [f'{e} AS "{n}"' for e, n in exprs]
        if age_bin_years > 0:
            keys.append(
                f"CAST(floor({age} / {int(age_bin_years)}) * {int(age_bin_years)} AS INTEGER) AS age_from_years"
            )
        stats = (
            "count(*) AS observations, count(DISTINCT (o.sc, o.sid)) AS sections, "
            "round(avg(o.v), 3) AS mean, round(median(o.v), 3) AS median, "
            "round(quantile_cont(o.v, 0.25), 3) AS p25, round(quantile_cont(o.v, 0.75), 3) AS p75, "
            "round(min(o.v), 3) AS min, round(max(o.v), 3) AS max"
        )
        base = f'FROM obs o JOIN "{SECTIONS}" g ON g."STATE_CODE" = o.sc AND g."SHRP_ID" = o.sid {where_sql(where)}'
        group_cols = ", ".join(f'"{n}"' for _, n in exprs) + (", age_from_years" if age_bin_years > 0 else "")
        rows = self.query(
            f"""WITH {cte}, grouped AS (SELECT {", ".join(keys)}, {stats} {base} GROUP BY ALL)
                SELECT *, count(*) OVER () AS _total FROM grouped ORDER BY {group_cols}
                LIMIT {page.limit} OFFSET {page.offset}""",
            params,
        )
        overall = self.query(f"WITH {cte} SELECT {stats} {base}", params)[0]
        total = int(rows[0]["_total"]) if rows else 0
        for r in rows:
            del r["_total"]
        return rows, total, overall

    def numeric_columns(self, table: str) -> list[str]:
        """Lower-case names of the numeric columns of a table."""
        numeric = {"DOUBLE", "BIGINT", "INTEGER", "FLOAT", "DECIMAL", "HUGEINT", "SMALLINT"}
        return [c.lower() for c, t in self.schema_of(table).items() if t.split("(")[0] in numeric]


__all__ = ["DuckDBRepository", "distance_km_sql", "section_where", "where_sql"]
