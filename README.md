# MCP Catalog Automation Lab

**Topic:** MCP Integration & Catalog Automation (CPG, all functions)
**Outcome:** Learners understand MCP architecture and can design catalog-automation workflows.
**Lab:** Design an MCP connection to a catalog tool and generate metadata for 3 tables.

This repo is a working lab. It runs on a laptop with no cloud account (a local SQLite "catalog"), and the same
server code switches to **Databricks Unity Catalog** or **Snowflake** by changing one environment variable.

Tested: 12 automated tests pass on `mcp` 1.30.0 and `mcp` 2.3.0 (Python 3.13).
Not tested here: the live Unity Catalog and Snowflake backends (no accounts available) and `client/agent.py`
against the live Claude API (no key available). The agent loop itself is tested with a scripted stand-in model.

---

## The idea in one picture

```
 You / Claude Desktop / Claude Code / agent.py            <- MCP HOST (+ client)
              |
              |  MCP over stdio (JSON-RPC)
              v
 catalog_mcp/server.py                                    <- MCP SERVER
   tools:      list_tables  describe_table  sample_rows  profile_column  propose_metadata
   resource:   glossary://cpg
   prompt:     document_table
   guardrails: allow-list, identifier check, PII masking, row cap, audit log
              |
              v
 backends/  sqlite (demo)  |  unity_backend  |  snowflake_backend      <- the catalog
              ^
              |  apply (write)  - only the human approval CLI can do this
 review/approve.py  <-- a person reads the proposal and approves it
```

The model can **read (masked)** and **propose**. It can never **write**. That single design decision is the heart of
safe catalog automation.

## Repo map

| Path | What it is |
|---|---|
| `catalog_mcp/server.py` | The MCP server: tools, resource, prompt |
| `catalog_mcp/security.py` | All guardrails: allow-list, PII masking, audit log |
| `catalog_mcp/backends/` | `sqlite_backend.py` (runs now), `unity_backend.py`, `snowflake_backend.py` |
| `client/offline_demo.py` | Runs the whole MCP conversation with no API key |
| `client/agent.py` | Claude as the metadata writer (tool-use loop over MCP) |
| `review/approve.py` | Human approval CLI: list, show, approve, reject, export to dbt YAML |
| `seed_data.py`, `data/glossary.md` | 3 CPG tables with cryptic names and PII, plus the abbreviation glossary |
| `tests/test_lab.py` | 12 end-to-end tests that start the real server |
| `docs/TEACHING_GUIDE.md` | The session script: talking points, demos, quiz |
| `docs/LAB_HANDOUT.md` | The lab worksheet with the design canvas |
| `docs/LEARNER_RUN_GUIDE.md` | Self-paced "how to run it yourself" guide for learners (Windows and Mac/Linux) |
| `docs/CONNECT_REAL_CATALOGS.md` | Databricks, Snowflake, dbt: managed vs custom servers, configs, grants |

---

## Step by step: run the lab

### Step 1. Set up (5 min)

```bash
cd mcp-catalog-lab
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`.env.example` only lists the available settings. The code reads real environment variables (`export` on Mac/Linux, `set` on Windows),
it does not load a `.env` file.

### Step 2. Create the demo catalog (1 min)

```bash
python seed_data.py
```

You get three CPG tables with deliberately unreadable names: `dim_product`, `dim_customer`, `fact_sales`
(columns like `prd_cd`, `net_rev_amt`, `trade_prm_flg`, `cust_email`).

### Step 3. Check the server is healthy (2 min)

```bash
pytest -q          # expect: 12 passed
```

### Step 4. See what the server advertises (5 min)

```bash
python - <<'EOF'
import asyncio
from client.session import open_session
async def go():
    async with open_session() as s:
        for t in (await s.list_tools()).tools: print("TOOL    ", t.name, "-", t.description)
        for r in (await s.list_resources()).resources: print("RESOURCE", r.uri)
        for p in (await s.list_prompts()).prompts: print("PROMPT  ", p.name)
asyncio.run(go())
EOF
```

Optional visual route: `npx @modelcontextprotocol/inspector python -m catalog_mcp.server` opens the MCP Inspector in a browser
(needs Node.js; set `PYTHONPATH` to the repo folder first).

### Step 5. Run the whole flow without an API key (3 min)

```bash
python -m client.offline_demo
```

This does exactly what a model would do: list tools, read the glossary, describe, sample, profile, then submit one proposal per
table. A rule-based writer plays the model, so the plumbing can be proven first. The last lines try two attacks (SQL injection in a
table name, a schema that is not on the allow-list) and show both are refused.

### Step 6. Let Claude write the metadata (10 min)

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # never commit this; use your secret manager in real life
python -m client.agent
```

Watch the log: Claude reads the glossary, describes each table, samples rows, profiles ambiguous columns and calls
`propose_metadata` once per table. Compare its descriptions with the rule-based ones from Step 5. That gap is the value of the model.

The default model is `claude-sonnet-5-5`; override with `ANTHROPIC_MODEL`.

### Step 7. Be the human reviewer (10 min)

```bash
python -m review.approve list
python -m review.approve show <proposal_id>
```

Low-confidence columns are flagged `<-- REVIEW`. Reject anything wrong:

```bash
python -m review.approve reject <proposal_id> --reviewer "Your Name" --note "tier_cd meaning is wrong"
```

### Step 8. Apply the approved metadata (3 min)

```bash
python -m review.approve approve <proposal_id> --reviewer "Your Name"        # refused: second lock not set
CATALOG_ALLOW_WRITE=1 python -m review.approve approve <proposal_id> --reviewer "Your Name"
python -m review.approve catalog                                             # the catalog is now documented
```

### Step 9. Ship it to dbt (5 min)

```bash
python -m review.approve export-dbt <proposal_id> > models/schema_dim_customer.yml
```

In a real dbt project this becomes a pull request. Same pattern: AI proposes, a person approves, Git is the audit trail.

### Step 10. Attack your own server (10 min)

Open `logs/audit.jsonl` and find your calls. Then try to break it: ask for 1000 sample rows, a table named
`dim_product; DROP TABLE x`, schema `finance`, the table `_catalog_metadata`. Every one should fail with a readable reason
(the tests in `tests/test_lab.py` automate exactly this).

### Step 11. Connect it to Claude Desktop or Claude Code (5 min)

See `configs/`. Then type: *"Use the document_table prompt for cpg.fact_sales."*

### Step 12 (stretch). Point it at a real catalog

Set `CATALOG_BACKEND=unity` or `snowflake` and follow `docs/CONNECT_REAL_CATALOGS.md`. Start with a **read-only** identity.

---

## Lab deliverables (what to collect from learners)

1. The completed **design canvas** (`docs/LAB_HANDOUT.md`, Part A).
2. The **approved metadata** for the 3 tables (screenshot of `review.approve catalog`).
3. A one-paragraph answer: *"Which control stopped which attack, and where in the code?"*

## Common problems

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: client` | Run commands from the repo root, with `python -m ...` |
| Client hangs at startup | Something in the server printed to **stdout**. Stdio MCP servers must log to stderr only |
| `isError` / `is_error` attribute errors | SDK version difference (1.x camelCase, 2.x snake_case). Use `client/session.py` helpers |
| `ImportError: FastMCP` | `mcp` 2.x renamed it `MCPServer`; `server.py` already handles both |
| Agent says it cannot find a table | Check `CATALOG_ALLOWED_SCHEMAS` and the glossary; read `logs/audit.jsonl` |
| Approve says "second lock" | Set `CATALOG_ALLOW_WRITE=1` for that one command, on purpose |
"# tiger_de" 
