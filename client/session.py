"""MCP client helpers: start the server as a subprocess and talk to it over stdio.

Security note: we pass the child process an explicit, minimal environment instead of our whole shell.
Secrets that the server does not need must not leak into it.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

# Only these variables are forwarded to the server process.
FORWARD_ENV = [
    "CATALOG_BACKEND", "CATALOG_ALLOWED_SCHEMAS", "CATALOG_MAX_SAMPLE_ROWS", "CATALOG_SQLITE_PATH",
    "CATALOG_AUDIT_LOG", "PROPOSALS_DIR",
    # real backends (read-only credentials only!)
    "DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET", "DATABRICKS_CATALOG", "DATABRICKS_WAREHOUSE_ID",
    "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_FILE", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE",
]


def server_params(extra_env: dict[str, str] | None = None) -> StdioServerParameters:
    env = {k: os.environ[k] for k in FORWARD_ENV if k in os.environ}
    env["PYTHONPATH"] = str(ROOT)
    env.update(extra_env or {})
    return StdioServerParameters(command=sys.executable, args=["-m", "catalog_mcp.server"], env=env, cwd=str(ROOT))


@asynccontextmanager
async def open_session(extra_env: dict[str, str] | None = None):
    async with stdio_client(server_params(extra_env)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _get(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    """mcp 1.x uses camelCase field names (isError), mcp 2.x uses snake_case (is_error). Support both."""
    if hasattr(obj, snake):
        return getattr(obj, snake)
    return getattr(obj, camel, default)


def is_error(result: Any) -> bool:
    return bool(_get(result, "is_error", "isError", False))


def input_schema(tool: Any) -> dict:
    return _get(tool, "input_schema", "inputSchema", {})


def result_text(result: Any) -> str:
    return "\n".join(getattr(b, "text", "") for b in result.content)


def result_obj(result: Any) -> dict:
    """Parse a tool result into a dict. Raises RuntimeError if the server flagged an error."""
    if is_error(result):
        raise RuntimeError(result_text(result))
    sc = _get(result, "structured_content", "structuredContent")
    if isinstance(sc, dict):
        return sc["result"] if set(sc) == {"result"} and isinstance(sc["result"], dict) else sc
    return json.loads(result_text(result))


async def call(session: ClientSession, name: str, **args: Any) -> dict:
    return result_obj(await session.call_tool(name, args))
