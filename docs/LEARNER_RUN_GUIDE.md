# Run the MCP Catalog Lab yourself

A self-paced guide. No cloud account needed. Allow about 60 minutes.

**The story in two lines:** a warehouse table full of unreadable columns (`prd_cd`, `net_rev_amt`, `cust_email`).
You will run a small MCP "front desk" that lets an AI draft descriptions for them, then act as the human who approves every word.

Every step has the command for **Windows (Command Prompt)** and for **Mac / Linux (Terminal)**, what you should see, and a checkpoint.
Use the same window for the whole lab. If you close it, repeat Step 1b (activate) and re-set any variables.

---

## What you need

- **Python 3.10 or newer.** Check with `python --version` (on some machines `python3 --version` or `py --version`).
- About 200 MB of free disk space.
- Optional, for Step 11 only: a Claude API key. Everything else runs without one.

---

## Step 0. Get the code

Ask your trainer for the repository link, then:

```
git clone <REPO-URL> mcp-catalog-lab
cd mcp-catalog-lab
```

No git? Download the ZIP from the repository page, extract it, and open a terminal inside the `mcp-catalog-lab` folder.

All commands below run from inside the `mcp-catalog-lab` folder.

---

## Step 1. Set up your environment (5 min)

**1a. Create a private Python environment**

| Windows (Command Prompt) | Mac / Linux |
|---|---|
| `python -m venv .venv` | `python3 -m venv .venv` |

**1b. Activate it** (your prompt will start with `(.venv)`)

| Windows (Command Prompt) | Mac / Linux |
|---|---|
| `.venv\Scripts\activate` | `source .venv/bin/activate` |

**1c. Install the requirements**

```
pip install -r requirements.txt
```

- [ ] Checkpoint: the install finishes without red errors.

---

## Step 2. Create the demo data (1 min)

```
python seed_data.py
```

You should see:

```
Created ...data/cpg_demo.db  (dim_product=40, dim_customer=30, fact_sales=500 rows)
```

You now have three CPG tables with deliberately cryptic names: `dim_product`, `dim_customer`, `fact_sales`.

- [ ] Checkpoint: the "Created" line appears.

---

## Step 3. Prove everything works (2 min)

```
pytest -q
```

You should see `12 passed`. These tests start the real MCP server and try to attack it, so a pass means the guardrails work on your machine.

- [ ] Checkpoint: `12 passed`.

---

## Step 4. Run the whole flow without any AI (3 min)

```
python -m client.offline_demo
```

This does exactly what an AI would do, with a simple rule-based writer standing in for it. Read the output top to bottom.

What to notice:

| In the output | What it means |
|---|---|
| `TOOLS : [...]` lists 7 names | The "menu" the front desk offers. There is no write tool. |
| `PROMPTS: ['document_table']` and `RESOURCE glossary://cpg` | A reusable instruction and a cheat sheet of abbreviations |
| `masked columns = ['cntct_nm', 'cust_email', 'cust_phn']` | Personal data is blacked out before anything leaves the server |
| `proposal -> {... "status": "pending_human_review"}` | Drafts go to a review tray. Nothing is published yet. |
| Last lines: `is_error=True` twice | A SQL-injection attempt and a blocked schema were both refused |

- [ ] Checkpoint: you see 3 proposals created and 2 refused attacks.

---

## Step 5. Look inside the front desk (5 min)

Open `catalog_mcp/server.py` in any editor (Notepad, VS Code).

Find these three things and write down the line numbers:

1. The function `describe_table`. Notice the type hints and the docstring. The AI reads that docstring to decide when to use the tool.
2. The function `propose_metadata`. Notice it only **proposes**.
3. Search the file for `update`, `write`, `execute`. You will not find a tool that changes the catalog. That absence is the safety design.

Then open `catalog_mcp/security.py` and find `check_ident` (blocks sneaky table names) and `mask_rows` (hides personal data).

- [ ] Checkpoint: you can say in one sentence why `propose_metadata` is safer than an `update_metadata` tool.

---

## Step 6. Become the human reviewer (8 min)

List the drafts waiting in the review tray:

```
python -m review.approve list
```

Pick one id from the list and save it in a variable:

| Windows (Command Prompt) | Mac / Linux |
|---|---|
| `set PROP=paste-the-id-here` | `PROP=paste-the-id-here` |

Read the draft:

| Windows | Mac / Linux |
|---|---|
| `python -m review.approve show %PROP%` | `python -m review.approve show $PROP` |

Columns marked `<-- REVIEW` are the ones the writer was unsure about. Read those first.

Find one description you would change and note why. To reject a draft:

| Windows | Mac / Linux |
|---|---|
| `python -m review.approve reject %PROP% --reviewer "Your Name" --note "reason"` | `python -m review.approve reject $PROP --reviewer "Your Name" --note "reason"` |

- [ ] Checkpoint: you wrote down one description you would change and why.

---

## Step 7. Approve and publish (5 min)

Try to publish **without** the second lock. It should refuse:

| Windows | Mac / Linux |
|---|---|
| `python -m review.approve approve %PROP% --reviewer "Your Name"` | `python -m review.approve approve $PROP --reviewer "Your Name"` |

Expected: `Refusing to write: set CATALOG_ALLOW_WRITE=1 (second lock).`

Now switch the lock on **for this one command**:

**Windows (Command Prompt)**, keep the quotes (without them a trailing space sneaks into the value and the check fails):

```
set "CATALOG_ALLOW_WRITE=1"
python -m review.approve approve %PROP% --reviewer "Your Name"
set CATALOG_ALLOW_WRITE=
```

**Mac / Linux**

```
CATALOG_ALLOW_WRITE=1 python -m review.approve approve $PROP --reviewer "Your Name"
```

See what the catalog holds now:

```
python -m review.approve catalog
```

The table you approved now shows plain-English descriptions. The others still say `(undocumented)`.

- [ ] Checkpoint: one table is documented, and you can explain why the first attempt was refused.

---

## Step 8. Export to dbt (3 min)

| Windows | Mac / Linux |
|---|---|
| `mkdir models` | `mkdir -p models` |
| `python -m review.approve export-dbt %PROP% > models\schema.yml` | `python -m review.approve export-dbt $PROP > models/schema.yml` |
| `type models\schema.yml` | `cat models/schema.yml` |

This is a ready-to-use dbt `schema.yml` block. In a real project it would become a pull request, so Git records who approved what.

- [ ] Checkpoint: you see `version: 2` and your column descriptions.

---

## Step 9. Try to break it (8 min)

```
pytest -v -k boundaries
```

You will see five attack cases, each marked `PASSED` because the server refused it: SQL injection, a path trick, a forbidden schema, the catalog's internal table, and a table that does not exist.

Now the privacy test:

```
pytest -v -k pii
```

Fill in this table in your notes:

| Attack | Which control stopped it? (look in `security.py` or the backend) |
|---|---|
| `dim_product; DROP TABLE x` | |
| `schema = finance` | |
| Asking for 1000 sample rows | |
| An email column labelled "other" | |

- [ ] Checkpoint: you can name the control behind each attack.

---

## Step 10. Read the logbook (2 min)

| Windows (Command Prompt) | Mac / Linux |
|---|---|
| `powershell -NoProfile -Command "Get-Content logs\audit.jsonl -Tail 5"` | `tail -5 logs/audit.jsonl` |

Every call is recorded with its time, tool, outcome and duration. Look for any customer email address in the log. There should be none.

- [ ] Checkpoint: you found your own earlier calls in the log.

---

## Step 11 (optional). Let Claude write the descriptions

Only if your trainer gave you an API key. Never paste a key into a file or share your screen while typing it.

**Windows (Command Prompt)**

```
del proposals\*.json
set ANTHROPIC_API_KEY=your-key-here
python -m client.agent
set ANTHROPIC_API_KEY=
```

**Mac / Linux**

```
rm -f proposals/*.json
export ANTHROPIC_API_KEY=your-key-here
python -m client.agent
unset ANTHROPIC_API_KEY
```

Watch the log: Claude reads the glossary, looks at each table, samples rows, profiles unclear columns, then proposes once per table. Run Steps 6 and 7 again on its drafts and compare them with the rule-based ones.

---

## Start over

| Windows | Mac / Linux |
|---|---|
| `del proposals\*.json` | `rm -f proposals/*.json` |
| `python seed_data.py` | `python seed_data.py` |

`seed_data.py` rebuilds the database, which also clears approved descriptions.

---

## If something goes wrong

| What you see | Fix |
|---|---|
| `python` is not recognised | Try `py` (Windows) or `python3` (Mac / Linux). Install Python 3.10+ if neither works. |
| `ModuleNotFoundError: client` | You are not inside the `mcp-catalog-lab` folder. Use `cd` to get there. |
| `ModuleNotFoundError: mcp` | The environment is not active. Repeat Step 1b, then `pip install -r requirements.txt`. |
| Activate command fails on Windows | Use Command Prompt. In PowerShell run `.venv\Scripts\Activate.ps1` instead. |
| Approve still refuses after setting the lock | On Windows, use `set "CATALOG_ALLOW_WRITE=1"` with the quotes. |
| `%PROP%` printed literally | You are in PowerShell, not Command Prompt. Use `$env:PROP="the-id"` and `$env:PROP`. |
| Tests hang | Close other terminals running the lab and retry. Ask your trainer if it persists. |

---

## What to hand in

1. Your completed notes from Step 5 (three line numbers), Step 6 (the description you would change) and Step 9 (the control table).
2. A screenshot of `python -m review.approve catalog` showing at least one documented table.
3. Three to five sentences: *If the AI were tricked by a malicious value hiding in the data, what is the most it could do in this design, and why?*
