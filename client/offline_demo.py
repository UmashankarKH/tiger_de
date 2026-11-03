"""Lab runner WITHOUT an API key.

It performs the exact same MCP conversation an LLM would (initialize -> list tools -> read the
glossary resource -> describe -> sample -> profile -> propose), but a deterministic rule-based
'writer' stands in for the model. Use it to prove the plumbing works before spending tokens.

    python -m client.offline_demo
"""
from __future__ import annotations

import asyncio
import json
import re

from .session import call, is_error, open_session, result_text

TABLES = ["dim_product", "dim_customer", "fact_sales"]


def parse_glossary(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^- (\w+): (.+)$", text, re.M)}


def classify(name: str, pii: bool) -> str:
    if pii:
        return "pii"
    if name.endswith("_flg"):
        return "flag"
    if name.endswith("_dt") or name.startswith("dt_"):
        return "date"
    if name.endswith("_amt") or name.startswith("qty_") or name.endswith("_ml"):
        return "measure"
    if name.endswith(("_cd", "_id")):
        return "key" if name in {"prd_cd", "cust_id", "sls_id", "dt_key"} else "dimension"
    return "dimension"


def words(name: str, gloss: dict[str, str]) -> str:
    return " ".join(gloss.get(t, t).split(" (")[0] for t in name.split("_"))


async def main() -> None:
    async with open_session() as s:
        tools = (await s.list_tools()).tools
        print("TOOLS :", [t.name for t in tools])
        print("PROMPTS:", [p.name for p in (await s.list_prompts()).prompts])
        gloss_text = (await s.read_resource("glossary://cpg")).contents[0].text
        gloss = parse_glossary(gloss_text)
        print(f"RESOURCE glossary://cpg -> {len(gloss)} terms\n")

        for table in TABLES:
            d = await call(s, "describe_table", schema="cpg", table=table)
            smp = await call(s, "sample_rows", schema="cpg", table=table, limit=3)
            print(f"== {table}: {d['row_count']} rows, masked columns = {smp['masked_columns']}")
            cols = []
            for c in d["columns"]:
                prof = await call(s, "profile_column", schema="cpg", table=table, column=c["name"])
                cls = classify(c["name"], prof["pii"])
                desc = words(c["name"], gloss).capitalize()
                if cls == "pii":
                    desc += " (personal data, restricted access)"
                if c["name"] in {"net_rev_amt"}:
                    desc = "Net revenue amount = gross revenue minus discount"
                cols.append({"name": c["name"], "description": desc + ".", "classification": cls,
                             "confidence": "medium" if cls != "dimension" else "low"})
            kind = "Dimension" if table.startswith("dim_") else "Fact"
            res = await call(s, "propose_metadata", schema="cpg", table=table,
                             table_description=f"{kind} table: {words(table.split('_', 1)[1], gloss)}.",
                             columns=cols)
            print("   proposal ->", json.dumps(res))

        print("\nPending proposals:", (await call(s, "list_proposals"))["proposals"])
        # Prove the security boundary
        print("\n-- Security checks --")
        for label, kwargs in [("injection in table name", dict(schema="cpg", table="dim_product; DROP TABLE x")),
                              ("schema not on allow-list", dict(schema="finance", table="dim_product"))]:
            r = await s.call_tool("describe_table", kwargs)
            print(f"{label}: is_error={is_error(r)} -> {result_text(r)[:90]}")


if __name__ == "__main__":
    asyncio.run(main())
