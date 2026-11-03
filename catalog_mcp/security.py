"""Security boundary for the catalog MCP server.

Everything in here is enforced INSIDE the server, so it holds no matter what the
LLM asks for, and no matter which backend (SQLite / Unity Catalog / Snowflake) is plugged in.

Teaching point: never rely on the prompt to keep data safe. Put the guardrail in code.
"""
from __future__ import annotations

import functools
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # mcp 1.x
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:  # mcp 2.x
    from mcp.server.mcpserver.exceptions import ToolError

ROOT = Path(__file__).resolve().parents[1]

# Only plain identifiers are ever allowed to reach a SQL string. This kills SQL injection
# through table / schema / column names, which the LLM controls.
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Column-name based PII detection (extend this list for your own naming standards).
PII_COLUMN_RE = re.compile(
    r"(email|e_mail|phn|phone|mobile|ssn|aadhaar|passport|dob|birth|addr|cntct|contact_n|first_n|last_n)",
    re.I,
)
# Value based detection, catches PII hiding in columns with innocent names.
EMAIL_VALUE_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE_VALUE_RE = re.compile(r"^\+?[\d\s\-()]{9,}$")

MASK = "<masked:pii>"
MAX_CELL_CHARS = 80  # long strings are a prompt-injection vector, so cap them


class SecurityError(ValueError):
    """Raised when a request crosses a security boundary. The message is safe to show the LLM."""


def check_ident(value: Any, kind: str = "identifier") -> str:
    if not isinstance(value, str) or not IDENT_RE.match(value):
        raise SecurityError(f"Invalid {kind}: only letters, digits and underscores are allowed.")
    return value


def allowed_schemas() -> set[str]:
    raw = os.getenv("CATALOG_ALLOWED_SCHEMAS", "cpg")
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def check_schema(schema: str) -> str:
    check_ident(schema, "schema")
    if schema.lower() not in allowed_schemas():
        raise SecurityError(
            f"Schema '{schema}' is not on the allow-list. Allowed: {sorted(allowed_schemas())}"
        )
    return schema


def max_sample_rows() -> int:
    return int(os.getenv("CATALOG_MAX_SAMPLE_ROWS", "5"))


def is_pii_column(name: str) -> bool:
    return bool(PII_COLUMN_RE.search(name))


DATE_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _looks_like_pii_value(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    if EMAIL_VALUE_RE.search(v):
        return True
    t = v.strip()
    # ISO dates are digit-and-dash strings too; do not mistake them for phone numbers.
    return bool(PHONE_VALUE_RE.match(t)) and not DATE_VALUE_RE.match(t) and sum(c.isdigit() for c in t) >= 10


def mask_scalar(v: Any) -> Any:
    if _looks_like_pii_value(v):
        return MASK
    if isinstance(v, str) and len(v) > MAX_CELL_CHARS:
        return v[:MAX_CELL_CHARS] + "...[truncated]"
    return v


def mask_rows(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Mask PII by column name first, then by value pattern. Returns (rows, masked_columns)."""
    masked_cols: set[str] = set()
    out = []
    for row in rows:
        new = {}
        for col, val in row.items():
            if is_pii_column(col):
                new[col] = MASK if val is not None else None
                masked_cols.add(col)
            else:
                m = mask_scalar(val)
                if m == MASK:
                    masked_cols.add(col)
                new[col] = m
        out.append(new)
    return out, sorted(masked_cols)


_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(s: str, max_len: int) -> str:
    """Sanitise free text the LLM wants to store in the catalog."""
    s = _CTRL_RE.sub("", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        raise SecurityError("Description must not be empty.")
    return s[:max_len]


# ---------------------------------------------------------------- audit log
def audit_path() -> Path:
    return Path(os.getenv("CATALOG_AUDIT_LOG", ROOT / "logs" / "audit.jsonl"))


def audit(event: str, **fields: Any) -> None:
    p = audit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _redact_args(kw: dict) -> dict:
    out = {}
    for k, v in kw.items():
        if isinstance(v, str):
            out[k] = v[:120]
        elif isinstance(v, (list, dict)):
            out[k] = f"<{type(v).__name__} len={len(v)}>"
        else:
            out[k] = v
    return out


def audited(fn):
    """Decorator: every tool call leaves a line in the audit log (who/what/when/outcome, never data)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            audit("tool_call", tool=fn.__name__, args=_redact_args(kwargs), status="ok",
                  ms=round((time.perf_counter() - t0) * 1000))
            return result
        except Exception as e:  # noqa: BLE001
            audit("tool_call", tool=fn.__name__, args=_redact_args(kwargs), status="error",
                  error=type(e).__name__, msg=str(e)[:200],
                  ms=round((time.perf_counter() - t0) * 1000))
            if isinstance(e, (SecurityError, FileNotFoundError)):
                # Safe, intentional messages are returned to the model so it can self-correct.
                raise ToolError(str(e)) from e
            raise  # anything else is an internal error: the SDK hides details from the client

    return wrapper


def log(msg: str) -> None:
    """stdio MCP servers must NEVER print to stdout (it is the protocol channel). Use stderr."""
    print(msg, file=sys.stderr, flush=True)
