"""The contract every catalog backend must satisfy.

The MCP server only talks to this interface. Swap SQLite for Unity Catalog or Snowflake
by changing one environment variable. The server code (and the LLM) never changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CatalogBackend(ABC):
    name = "abstract"

    # ---- read side (used by MCP tools) -------------------------------------------------
    @abstractmethod
    def list_schemas(self) -> list[str]: ...

    @abstractmethod
    def list_tables(self, schema: str) -> list[dict[str, Any]]:
        """[{'name': str, 'comment': str | None}]"""

    @abstractmethod
    def describe_table(self, schema: str, table: str) -> dict[str, Any]:
        """{'schema','table','comment','row_count','columns':[{'name','type','nullable','comment'}]}"""

    @abstractmethod
    def sample_rows(self, schema: str, table: str, limit: int) -> list[dict[str, Any]]: ...

    @abstractmethod
    def column_stats(self, schema: str, table: str, column: str, include_values: bool) -> dict[str, Any]:
        """{'null_pct','distinct_count', and if include_values: 'min','max','top_values'}"""

    # ---- write side (NOT exposed as an MCP tool; only the human approval CLI calls this) --
    @abstractmethod
    def apply_metadata(
        self,
        schema: str,
        table: str,
        table_comment: str,
        columns: list[dict[str, Any]],
        reviewer: str,
        proposal_id: str,
    ) -> dict[str, Any]: ...
