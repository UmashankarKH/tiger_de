"""Local demo backend. Behaves like a tiny data catalog so the lab runs on any laptop, no cloud needed.

Read connections are opened READ-ONLY at the database level (defence in depth).
Comments and tags live in an internal table, the same way a real catalog stores them.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..security import SecurityError, check_ident
from .base import CatalogBackend


class SQLiteBackend(CatalogBackend):
    name = "sqlite-demo"
    SCHEMA = "cpg"

    def __init__(self, path: str):
        self.path = str(path)

    # -- connections ----------------------------------------------------------------
    def _ro(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def _rw(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _check(self, schema: str, table: str | None = None) -> None:
        if schema.lower() != self.SCHEMA:
            raise SecurityError(f"Unknown schema '{schema}'.")
        if table is not None:
            check_ident(table, "table")
            with self._ro() as con:
                ok = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? AND name NOT LIKE '\\_%' ESCAPE '\\'",
                    (table,),
                ).fetchone()
            if not ok:
                raise SecurityError(f"Table '{schema}.{table}' not found.")

    # -- read side --------------------------------------------------------------------
    def list_schemas(self) -> list[str]:
        return [self.SCHEMA]

    def _comments(self, con, table: str) -> dict[str | None, str]:
        try:
            rows = con.execute(
                "SELECT column_name, comment FROM _catalog_metadata WHERE table_name=?", (table,)
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {r["column_name"]: r["comment"] for r in rows}

    def list_tables(self, schema: str) -> list[dict[str, Any]]:
        self._check(schema)
        with self._ro() as con:
            names = [
                r["name"]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\' ORDER BY name"
                )
            ]
            return [{"name": n, "comment": self._comments(con, n).get(None)} for n in names]

    def describe_table(self, schema: str, table: str) -> dict[str, Any]:
        self._check(schema, table)
        with self._ro() as con:
            cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            comments = self._comments(con, table)
            count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        return {
            "schema": schema,
            "table": table,
            "comment": comments.get(None),
            "row_count": count,
            "columns": [
                {"name": c["name"], "type": c["type"], "nullable": not c["notnull"], "comment": comments.get(c["name"])}
                for c in cols
            ],
        }

    def sample_rows(self, schema: str, table: str, limit: int) -> list[dict[str, Any]]:
        self._check(schema, table)
        with self._ro() as con:
            return [dict(r) for r in con.execute(f'SELECT * FROM "{table}" LIMIT ?', (int(limit),))]

    def column_stats(self, schema: str, table: str, column: str, include_values: bool) -> dict[str, Any]:
        self._check(schema, table)
        check_ident(column, "column")
        with self._ro() as con:
            names = {c["name"] for c in con.execute(f'PRAGMA table_info("{table}")')}
            if column not in names:
                raise SecurityError(f"Column '{column}' not found in {table}.")
            total, nulls, distinct = con.execute(
                f'SELECT COUNT(*), SUM("{column}" IS NULL), COUNT(DISTINCT "{column}") FROM "{table}"'
            ).fetchone()
            out: dict[str, Any] = {
                "null_pct": round(100.0 * (nulls or 0) / total, 2) if total else 0.0,
                "distinct_count": distinct,
            }
            if include_values:
                mn, mx = con.execute(f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"').fetchone()
                top = con.execute(
                    f'SELECT "{column}" AS v, COUNT(*) AS n FROM "{table}" WHERE "{column}" IS NOT NULL '
                    f"GROUP BY 1 ORDER BY n DESC LIMIT 5"
                ).fetchall()
                out.update({"min": mn, "max": mx, "top_values": [{"value": r["v"], "count": r["n"]} for r in top]})
            return out

    # -- write side (human approval path only) ----------------------------------------
    def apply_metadata(self, schema, table, table_comment, columns, reviewer, proposal_id):
        self._check(schema, table)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        real = {c["name"] for c in self.describe_table(schema, table)["columns"]}
        with self._rw() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS _catalog_metadata(
                       table_name TEXT, column_name TEXT, comment TEXT, tags TEXT,
                       reviewed_by TEXT, proposal_id TEXT, updated_at TEXT,
                       PRIMARY KEY (table_name, column_name))"""
            )
            con.execute(
                "INSERT OR REPLACE INTO _catalog_metadata VALUES (?,?,?,?,?,?,?)",
                (table, None, table_comment, json.dumps({"ai_generated": "true"}), reviewer, proposal_id, now),
            )
            applied = 0
            for c in columns:
                if c["name"] not in real:
                    continue
                tags = {"ai_generated": "true", "classification": c.get("classification", "other")}
                con.execute(
                    "INSERT OR REPLACE INTO _catalog_metadata VALUES (?,?,?,?,?,?,?)",
                    (table, c["name"], c["description"], json.dumps(tags), reviewer, proposal_id, now),
                )
                applied += 1
        return {"table": f"{schema}.{table}", "columns_written": applied}
