"""Tiny file-based proposal queue. The LLM can only ADD to it. A human moves items out of it.

In production replace this with a table, a Jira ticket or a Git pull request: anything with an owner and an audit trail.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import ROOT


def _dir() -> Path:
    d = Path(os.getenv("PROPOSALS_DIR", ROOT / "proposals"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def create(payload: dict[str, Any]) -> str:
    pid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    rec = {"id": pid, "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}
    (_dir() / f"{pid}.json").write_text(json.dumps(rec, indent=2))
    return pid


def get(pid: str) -> dict[str, Any]:
    p = _dir() / f"{Path(pid).name}.json"  # Path().name blocks path traversal like ../../etc/passwd
    if not p.exists():
        raise FileNotFoundError(f"No proposal '{pid}'")
    return json.loads(p.read_text())


def list_all(status: str | None = None) -> list[dict[str, Any]]:
    items = [json.loads(p.read_text()) for p in sorted(_dir().glob("*.json"))]
    return [i for i in items if status is None or i["status"] == status]


def set_status(pid: str, status: str, reviewer: str, note: str = "") -> dict[str, Any]:
    rec = get(pid)
    rec.update(status=status, reviewed_by=reviewer, review_note=note,
               reviewed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    (_dir() / f"{pid}.json").write_text(json.dumps(rec, indent=2))
    return rec
