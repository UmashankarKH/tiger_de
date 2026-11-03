"""Snowflake backend (snowflake-connector-python).

STATUS: written against the documented connector API but NOT run against a live account in this repo.
Test it with a read-only role first.

Auth: key-pair auth for a service user is the recommended pattern for non-interactive servers.
Needed env:
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY_FILE, SNOWFLAKE_ROLE,
  SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE

Role for the MCP server (read):   USAGE on database/schema/warehouse, SELECT on tables (or REFERENCES for metadata only)
Role for the approval CLI (write): OWNERSHIP or ALTER on the target tables.  Use a DIFFERENT role.
"""
from __future__ import annotations

import os
from typing import Any

from ..security import check_ident
from .base import CatalogBackend


def _lit(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


class SnowflakeBackend(CatalogBackend):
    name = "snowflake"

    def __init__(self):
        import snowflake.connector  # pip install snowflake-connector-python

        self.db = check_ident(os.environ["SNOWFLAKE_DATABASE"], "database")
        self.con = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"],
            role=os.environ["SNOWFLAKE_ROLE"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            database=self.db,
            session_parameters={"QUERY_TAG": "mcp-catalog-lab"},
        )

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self.con.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []
        finally:
            cur.close()

    def _fq(self, schema: str, table: str) -> str:
        return f"{self.db}.{check_ident(schema, 'schema')}.{check_ident(table, 'table')}"

    def list_schemas(self) -> list[str]:
        return [r[0] for r in self._q(f"SELECT SCHEMA_NAME FROM {self.db}.INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA'")]

    def list_tables(self, schema: str) -> list[dict[str, Any]]:
        rows = self._q(
            f"SELECT TABLE_NAME, COMMENT FROM {self.db}.INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = UPPER(%s) ORDER BY 1",
            (schema,),
        )
        return [{"name": r[0], "comment": r[1]} for r in rows]

    def describe_table(self, schema: str, table: str) -> dict[str, Any]:
        fq = self._fq(schema, table)
        t = self._q(
            f"SELECT COMMENT FROM {self.db}.INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=UPPER(%s) AND TABLE_NAME=UPPER(%s)",
            (schema, table),
        )
        cols = self._q(
            f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COMMENT FROM {self.db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA=UPPER(%s) AND TABLE_NAME=UPPER(%s) ORDER BY ORDINAL_POSITION",
            (schema, table),
        )
        count = self._q(f"SELECT COUNT(*) FROM {fq}")[0][0]
        return {
            "schema": schema, "table": table, "comment": t[0][0] if t else None, "row_count": int(count),
            "columns": [{"name": c[0], "type": c[1], "nullable": c[2] == "YES", "comment": c[3]} for c in cols],
        }

    def sample_rows(self, schema: str, table: str, limit: int) -> list[dict[str, Any]]:
        cur = self.con.cursor()
        try:
            cur.execute(f"SELECT * FROM {self._fq(schema, table)} LIMIT {int(limit)}")
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]
        finally:
            cur.close()

    def column_stats(self, schema: str, table: str, column: str, include_values: bool) -> dict[str, Any]:
        fq, c = self._fq(schema, table), check_ident(column, "column")
        total, nulls, distinct = self._q(f"SELECT COUNT(*), COUNT_IF({c} IS NULL), COUNT(DISTINCT {c}) FROM {fq}")[0]
        out: dict[str, Any] = {"null_pct": round(100.0 * nulls / total, 2) if total else 0.0, "distinct_count": int(distinct)}
        if include_values:
            mn, mx = self._q(f"SELECT MIN({c})::STRING, MAX({c})::STRING FROM {fq}")[0]
            top = self._q(f"SELECT {c}::STRING, COUNT(*) n FROM {fq} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 5")
            out.update({"min": mn, "max": mx, "top_values": [{"value": v, "count": int(n)} for v, n in top]})
        return out

    def apply_metadata(self, schema, table, table_comment, columns, reviewer, proposal_id):
        fq = self._fq(schema, table)
        self._q(f"COMMENT ON TABLE {fq} IS {_lit(table_comment)}")
        n = 0
        for c in columns:
            col = check_ident(c["name"], "column")
            self._q(f"COMMENT ON COLUMN {fq}.{col} IS {_lit(c['description'])}")
            n += 1
        # Tags need a pre-created tag object, e.g.  CREATE TAG governance.tags.classification;
        tag_ns = os.getenv("SNOWFLAKE_TAG_NAMESPACE")  # e.g. GOVERNANCE.TAGS
        if tag_ns:
            for c in columns:
                col = check_ident(c["name"], "column")
                self._q(f"ALTER TABLE {fq} MODIFY COLUMN {col} SET TAG {tag_ns}.CLASSIFICATION = {_lit(c.get('classification', 'other'))}")
        return {"table": f"{schema}.{table}", "columns_written": n}
