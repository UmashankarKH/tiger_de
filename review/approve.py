"""Human-in-the-loop approval. This is the ONLY code path that writes to the catalog.

    python -m review.approve list
    python -m review.approve show   <proposal_id>
    python -m review.approve approve <proposal_id> --reviewer "Your Name"
    python -m review.approve reject  <proposal_id> --reviewer "Your Name" --note "why"
    python -m review.approve catalog                     # show what the catalog holds now
    python -m review.approve export-dbt <proposal_id>    # print a dbt schema.yml block

Second lock: writing requires CATALOG_ALLOW_WRITE=1. In production this process also uses a DIFFERENT
credential (a write-capable role) from the MCP server (read-only role).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from catalog_mcp import proposals
from catalog_mcp.backends import get_backend
from catalog_mcp.security import audit


def cmd_list(_a):
    for p in proposals.list_all():
        print(f"{p['id']}  {p['status']:9}  {p['schema']}.{p['table']}  ({len(p['columns'])} columns)")


def cmd_show(a):
    p = proposals.get(a.id)
    print(f"{p['schema']}.{p['table']}  [{p['status']}]\n{p['table_description']}\n")
    for c in p["columns"]:
        flag = "  <-- REVIEW" if c["confidence"] == "low" else ""
        print(f"  {c['name']:<16} {c['classification']:<9} {c['confidence']:<6} {c['description']}{flag}")
    if p["server_overrides"]:
        print("\nServer overrides:", *p["server_overrides"], sep="\n  ")


def cmd_approve(a):
    if os.getenv("CATALOG_ALLOW_WRITE") != "1":
        sys.exit("Refusing to write: set CATALOG_ALLOW_WRITE=1 (second lock).")
    p = proposals.get(a.id)
    if p["status"] != "pending":
        sys.exit(f"Proposal is already {p['status']}.")
    res = get_backend().apply_metadata(p["schema"], p["table"], p["table_description"], p["columns"], a.reviewer, a.id)
    proposals.set_status(a.id, "applied", a.reviewer)
    audit("metadata_applied", proposal=a.id, table=f"{p['schema']}.{p['table']}", reviewer=a.reviewer)
    print("Applied:", json.dumps(res))


def cmd_reject(a):
    proposals.set_status(a.id, "rejected", a.reviewer, a.note)
    audit("metadata_rejected", proposal=a.id, reviewer=a.reviewer)
    print("Rejected.")


def cmd_export_dbt(a):
    """Turn a proposal into a dbt schema.yml block, ready for a pull request on your dbt project."""
    p = proposals.get(a.id)
    q = json.dumps  # a JSON string is a valid double-quoted YAML scalar
    lines = ["version: 2", "models:", f"  - name: {p['table']}", f"    description: {q(p['table_description'])}", "    columns:"]
    for c in p["columns"]:
        lines += [f"      - name: {c['name']}", f"        description: {q(c['description'])}",
                  "        meta:", f"          classification: {c['classification']}", "          ai_generated: true"]
    print("\n".join(lines))


def cmd_catalog(_a):
    b = get_backend()
    for t in b.list_tables("cpg"):
        d = b.describe_table("cpg", t["name"])
        print(f"\n{d['table']}: {d['comment'] or '(undocumented)'}")
        for c in d["columns"]:
            print(f"   {c['name']:<16} {c['comment'] or '-'}")


def main():
    ap = argparse.ArgumentParser(prog="review.approve")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)
    s = sub.add_parser("export-dbt"); s.add_argument("id"); s.set_defaults(fn=cmd_export_dbt)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("approve"); s.add_argument("id"); s.add_argument("--reviewer", required=True); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("reject"); s.add_argument("id"); s.add_argument("--reviewer", required=True); s.add_argument("--note", default=""); s.set_defaults(fn=cmd_reject)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
