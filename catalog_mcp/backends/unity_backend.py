"""Databricks Unity Catalog backend (databricks-sdk).

STATUS: written against the documented SDK API but NOT run against a live workspace in this repo.
Test it in your own workspace with a read-only service principal first.

Auth: the SDK reads DATABRICKS_HOST + (DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET for OAuth M2M)
or a CLI profile. Never put tokens in code, in the MCP config file, or in tool output.

Needed env:
  DATABRICKS_CATALOG       catalog to document, e.g. cpg_prod
  DATABRICKS_WAREHOUSE_ID  SQL warehouse used for COUNT / SAMPLE / COMMENT statements

Grants for the READ service principal:  USE CATALOG, USE SCHEMA, SELECT (or BROWSE for metadata only)
Grants for the WRITE principal (approval CLI only):  MODIFY / APPLY TAG on the target tables
"""
from __future__ import annotations

import os
from typing import Any

from ..security import SecurityError, check_ident
from .base import CatalogBackend


def _lit(s: str) -> str:
    """Spark SQL string literal. Escape backslash and single quote with a backslash.
    (Do NOT double the quote: Spark treats 'a''b' as two adjacent literals.)"""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


class UnityCatalogBackend(CatalogBackend):
    name = "databricks-unity-catalog"

    def __init__(self, catalog: str | None = None, warehouse_id: str | None = None):
        from databricks.sdk import WorkspaceClient  # pip install databricks-sdk

        self.catalog = check_ident(catalog or os.environ["DATABRICKS_CATALOG"], "catalog")
        self.warehouse_id = warehouse_id or os.environ["DATABRICKS_WAREHOUSE_ID"]
        self.w = WorkspaceClient()

    # -- helpers ----------------------------------------------------------------------
    def _fq(self, schema: str, table: str) -> str:
        check_ident(schema, "schema")
        check_ident(table, "table")
        return f"`{self.catalog}`.`{schema}`.`{table}`"

    def _sql(self, statement: str) -> list[list[Any]]:
        r = self.w.statement_execution.execute_statement(
            statement=statement, warehouse_id=self.warehouse_id, wait_timeout="30s"
        )
        state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
        if state != "SUCCEEDED":
            raise RuntimeError(f"Statement {state}: {getattr(r.status.error, 'message', '')}")
        return (r.result.data_array if r.result and r.result.data_array else []) or []

    # -- read side --------------------------------------------------------------------
    def list_schemas(self) -> list[str]:
        return [s.name for s in self.w.schemas.list(catalog_name=self.catalog) if s.name != "information_schema"]

    def list_tables(self, schema: str) -> list[dict[str, Any]]:
        check_ident(schema, "schema")
        return [{"name": t.name, "comment": t.comment} for t in self.w.tables.list(catalog_name=self.catalog, schema_name=schema)]

    def describe_table(self, schema: str, table: str) -> dict[str, Any]:
        fq = self._fq(schema, table)
        t = self.w.tables.get(full_name=f"{self.catalog}.{schema}.{table}")
        count = int(self._sql(f"SELECT COUNT(*) FROM {fq}")[0][0])
        return {
            "schema": schema,
            "table": table,
            "comment": t.comment,
            "row_count": count,
            "columns": [
                {"name": c.name, "type": c.type_text, "nullable": c.nullable, "comment": c.comment}
                for c in (t.columns or [])
            ],
        }

    def sample_rows(self, schema: str, table: str, limit: int) -> list[dict[str, Any]]:
        fq = self._fq(schema, table)
        cols = [c["name"] for c in self.describe_table(schema, table)["columns"]]
        rows = self._sql(f"SELECT * FROM {fq} LIMIT {int(limit)}")
        return [dict(zip(cols, r)) for r in rows]

    def column_stats(self, schema: str, table: str, column: str, include_values: bool) -> dict[str, Any]:
        fq = self._fq(schema, table)
        check_ident(column, "column")
        c = f"`{column}`"
        total, nulls, distinct = self._sql(
            f"SELECT COUNT(*), SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END), COUNT(DISTINCT {c}) FROM {fq}"
        )[0]
        total, nulls = int(total), int(nulls or 0)
        out: dict[str, Any] = {"null_pct": round(100.0 * nulls / total, 2) if total else 0.0, "distinct_count": int(distinct)}
        if include_values:
            mn, mx = self._sql(f"SELECT CAST(MIN({c}) AS STRING), CAST(MAX({c}) AS STRING) FROM {fq}")[0]
            top = self._sql(
                f"SELECT CAST({c} AS STRING), COUNT(*) n FROM {fq} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 5"
            )
            out.update({"min": mn, "max": mx, "top_values": [{"value": v, "count": int(n)} for v, n in top]})
        return out

    # -- write side (approval CLI only, run with a separate WRITE principal) -----------
    def apply_metadata(self, schema, table, table_comment, columns, reviewer, proposal_id):
        fq = self._fq(schema, table)
        real = {c["name"] for c in self.describe_table(schema, table)["columns"]}
        self._sql(f"COMMENT ON TABLE {fq} IS {_lit(table_comment)}")
        self._sql(f"ALTER TABLE {fq} SET TAGS ('ai_generated' = 'true', 'reviewed_by' = {_lit(reviewer)})")
        n = 0
        for c in columns:
            if c["name"] not in real:
                raise SecurityError(f"Unknown column {c['name']}")
            col = f"`{check_ident(c['name'], 'column')}`"
            self._sql(f"ALTER TABLE {fq} ALTER COLUMN {col} COMMENT {_lit(c['description'])}")
            self._sql(
                f"ALTER TABLE {fq} ALTER COLUMN {col} SET TAGS ('classification' = {_lit(c.get('classification', 'other'))})"
            )
            n += 1
        return {"table": f"{schema}.{table}", "columns_written": n}
