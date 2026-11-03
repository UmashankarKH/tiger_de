"""Backend factory. Pick the catalog with CATALOG_BACKEND=sqlite|unity|snowflake."""
from __future__ import annotations

import os

from ..security import ROOT
from .base import CatalogBackend


def get_backend() -> CatalogBackend:
    kind = os.getenv("CATALOG_BACKEND", "sqlite").lower()
    if kind == "sqlite":
        from .sqlite_backend import SQLiteBackend

        return SQLiteBackend(os.getenv("CATALOG_SQLITE_PATH", str(ROOT / "data" / "cpg_demo.db")))
    if kind == "unity":
        from .unity_backend import UnityCatalogBackend

        return UnityCatalogBackend()
    if kind == "snowflake":
        from .snowflake_backend import SnowflakeBackend

        return SnowflakeBackend()
    raise ValueError(f"Unknown CATALOG_BACKEND '{kind}'")
