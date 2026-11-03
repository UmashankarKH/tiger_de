"""End-to-end tests: they start the real MCP server over stdio and talk to it like any MCP client.

    pytest -q
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.session import call, is_error, open_session, result_text

ROOT = Path(__file__).resolve().parents[1]
GOOD_COLS = lambda cols: [{"name": c, "description": f"Desc of {c}", "classification": "other", "confidence": "high"} for c in cols]


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "demo.db"
    subprocess.run([sys.executable, str(ROOT / "seed_data.py"), str(db)], check=True, capture_output=True)
    return {"CATALOG_SQLITE_PATH": str(db), "PROPOSALS_DIR": str(tmp_path / "prop"), "CATALOG_AUDIT_LOG": str(tmp_path / "audit.jsonl")}


def run(coro):
    return asyncio.run(coro)


def test_discovery_exposes_expected_primitives_and_no_write_tool(env):
    async def go():
        async with open_session(env) as s:
            names = {t.name for t in (await s.list_tools()).tools}
            assert {"list_tables", "describe_table", "sample_rows", "profile_column", "propose_metadata"} <= names
            # the security design: there is NO tool that writes to the catalog
            assert not any(n.startswith(("apply", "write", "update", "delete", "drop", "execute", "run_sql")) for n in names)
            assert "document_table" in {p.name for p in (await s.list_prompts()).prompts}
            g = (await s.read_resource("glossary://cpg")).contents[0].text
            assert "prd: product" in g
    run(go())


def test_pii_is_masked_in_samples_and_profiles(env):
    async def go():
        async with open_session(env) as s:
            r = await call(s, "sample_rows", schema="cpg", table="dim_customer", limit=50)
            assert len(r["rows"]) <= 5  # server caps the limit, whatever the model asks for
            assert set(r["masked_columns"]) >= {"cust_email", "cust_phn", "cntct_nm"}
            assert all("@" not in str(row["cust_email"]) for row in r["rows"])
            p = await call(s, "profile_column", schema="cpg", table="dim_customer", column="cust_email")
            assert p["pii"] is True and "top_values" not in p
            # dates must NOT be mistaken for phone numbers
            d = await call(s, "sample_rows", schema="cpg", table="dim_product", limit=3)
            assert "lnch_dt" not in d["masked_columns"]
    run(go())


@pytest.mark.parametrize("kwargs", [
    dict(schema="cpg", table="dim_product; DROP TABLE dim_product"),
    dict(schema="cpg", table="../etc/passwd"),
    dict(schema="finance", table="dim_product"),
    dict(schema="cpg", table="_catalog_metadata"),
    dict(schema="cpg", table="no_such_table"),
])
def test_boundaries_reject_bad_requests_with_a_readable_error(env, kwargs):
    async def go():
        async with open_session(env) as s:
            r = await s.call_tool("describe_table", kwargs)
            assert is_error(r)
            assert result_text(r)  # model gets a reason it can act on
    run(go())


def test_propose_validates_and_never_touches_catalog(env):
    async def go():
        async with open_session(env) as s:
            d = await call(s, "describe_table", schema="cpg", table="dim_customer")
            cols = [c["name"] for c in d["columns"]]
            # unknown column -> rejected
            bad = await s.call_tool("propose_metadata", dict(schema="cpg", table="dim_customer", table_description="x", columns=GOOD_COLS(["ghost"])))
            assert is_error(bad)
            # model labels an email column as 'other' -> server forces 'pii'
            ok = await call(s, "propose_metadata", schema="cpg", table="dim_customer", table_description="Customer master", columns=GOOD_COLS(cols[:2] + ["cust_email"]))
            assert ok["status"] == "pending_human_review"
            assert any("cust_email" in o for o in ok["server_overrides"])
            assert "credit_lmt_amt" in ok["uncovered_columns"]
            # catalog still undocumented
            after = await call(s, "describe_table", schema="cpg", table="dim_customer")
            assert after["comment"] is None and all(c["comment"] is None for c in after["columns"])
    run(go())


def test_audit_log_records_calls_without_data(env):
    async def go():
        async with open_session(env) as s:
            await call(s, "sample_rows", schema="cpg", table="dim_customer", limit=2)
            await s.call_tool("describe_table", dict(schema="finance", table="x"))
    run(go())
    lines = [json.loads(l) for l in Path(env["CATALOG_AUDIT_LOG"]).read_text().splitlines()]
    assert {l["status"] for l in lines} == {"ok", "error"}
    assert "@example.com" not in Path(env["CATALOG_AUDIT_LOG"]).read_text()


def test_human_approval_is_the_only_write_path(env):
    async def go():
        async with open_session(env) as s:
            cols = [c["name"] for c in (await call(s, "describe_table", schema="cpg", table="dim_product"))["columns"]]
            return (await call(s, "propose_metadata", schema="cpg", table="dim_product", table_description="Product master", columns=GOOD_COLS(cols)))["proposal_id"]
    pid = run(go())
    base = {**os.environ, **env, "PYTHONPATH": str(ROOT)}
    # without the second lock -> refused
    r = subprocess.run([sys.executable, "-m", "review.approve", "approve", pid, "--reviewer", "tester"], cwd=ROOT, env=base, capture_output=True, text=True)
    assert r.returncode != 0 and "CATALOG_ALLOW_WRITE" in (r.stderr + r.stdout)
    # with the lock -> applied
    r = subprocess.run([sys.executable, "-m", "review.approve", "approve", pid, "--reviewer", "tester"], cwd=ROOT, env={**base, "CATALOG_ALLOW_WRITE": "1"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(env["CATALOG_SQLITE_PATH"])
    assert con.execute("SELECT comment FROM _catalog_metadata WHERE table_name='dim_product' AND column_name IS NULL").fetchone()[0] == "Product master"
    assert con.execute("SELECT COUNT(*) FROM _catalog_metadata WHERE table_name='dim_product'").fetchone()[0] == 10  # 1 table row + 9 column rows
    # approving twice is refused
    r = subprocess.run([sys.executable, "-m", "review.approve", "approve", pid, "--reviewer", "tester"], cwd=ROOT, env={**base, "CATALOG_ALLOW_WRITE": "1"}, capture_output=True, text=True)
    assert r.returncode != 0


def test_agent_loop_with_a_scripted_fake_model(env):
    """Proves the agent wiring (tool_use -> MCP -> tool_result) without an API key."""
    from client.agent import run_agent

    def tu(i, name, **inp):
        return SimpleNamespace(type="tool_use", id=f"t{i}", name=name, input=inp)

    script = [
        [tu(1, "describe_table", schema="cpg", table="dim_product")],
        [tu(2, "sample_rows", schema="cpg", table="dim_product", limit=3)],
        [tu(3, "propose_metadata", schema="cpg", table="dim_product", table_description="Product master",
            columns=GOOD_COLS(["prd_cd", "prd_nm", "brnd_cd", "catg_cd", "pack_sz_ml", "uom", "std_cost_amt", "lnch_dt", "actv_flg"]))],
    ]
    calls = iter(script)

    class FakeMessages:
        def create(self, **kw):
            try:
                return SimpleNamespace(stop_reason="tool_use", content=next(calls))
            except StopIteration:
                return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="done")])

    trace = run(run_agent(SimpleNamespace(messages=FakeMessages()), ["dim_product"], verbose=False, extra_env=env))
    assert [t["tool"] for t in trace] == ["describe_table", "sample_rows", "propose_metadata"]
    assert not any(t["is_error"] for t in trace)


def test_export_dbt_yaml_is_valid(env):
    yaml = pytest.importorskip("yaml")

    async def go():
        async with open_session(env) as s:
            cols = [c["name"] for c in (await call(s, "describe_table", schema="cpg", table="dim_product"))["columns"]]
            return (await call(s, "propose_metadata", schema="cpg", table="dim_product", table_description='Product "master"', columns=GOOD_COLS(cols)))["proposal_id"]
    pid = run(go())
    r = subprocess.run([sys.executable, "-m", "review.approve", "export-dbt", pid], cwd=ROOT, env={**os.environ, **env, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True)
    doc = yaml.safe_load(r.stdout)
    assert doc["models"][0]["name"] == "dim_product" and len(doc["models"][0]["columns"]) == 9
    assert doc["models"][0]["description"] == 'Product "master"'
