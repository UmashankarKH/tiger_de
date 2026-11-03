# Lab handout: Design an MCP connection to a catalog tool and generate metadata for 3 tables

**Time:** 70 minutes. **Work in groups of 3 or 4**, mixing business and technical people.

## Scenario
Your CPG company has a warehouse full of tables that nobody can read: `prd_cd`, `net_rev_amt`, `trade_prm_flg`, `cust_email`.
Analysts waste hours asking "what does this column mean?". You will design, build and test a safe way for Claude to draft the
documentation, with a person approving every word.

---

## Part A. Design on paper (15 min)

Fill in this canvas. Be specific. "Secure" is not an answer; "read-only service principal" is.

| # | Question | Your answer |
|---|---|---|
| 1 | Which catalog will you connect to, and why? (Unity Catalog / Snowflake / dbt) | |
| 2 | Managed MCP server or custom? Why? | |
| 3 | What identity does the server use, and what exactly may it do? | |
| 4 | List the **tools** the model gets (name + one-line purpose). Which tools did you deliberately leave out? | |
| 5 | What goes in a **resource** (context) and what goes in a **prompt** (reusable instruction)? | |
| 6 | Which schemas are allowed? Which columns count as PII, and what happens to them? | |
| 7 | Who reviews the AI output, in what order, and what do they do with low-confidence items? | |
| 8 | What gets logged, and what must never be logged? | |
| 9 | How will you know it is working? (one number) | |
| 10 | What is the worst thing that could happen, and which control stops it? | |

Business participants: your most valuable contribution is questions 5, 6 and 7. What does "net revenue" mean to Finance? Who in your function should approve descriptions?

---

## Part B. Build and run (35 min)

Follow **README.md steps 1 to 9**. At each checkpoint, tick the box.

- [ ] `pytest -q` shows `12 passed`
- [ ] You can name the 7 tools, 1 resource and 1 prompt the server exposes
- [ ] `python -m client.offline_demo` created three proposals
- [ ] (With API key) `python -m client.agent` created proposals written by Claude
- [ ] You read at least one proposal with `review.approve show` and found a column that needed a human decision
- [ ] You approved the 3 tables and `review.approve catalog` shows descriptions
- [ ] You exported one table to dbt YAML

### Your review notes
For each table write down: how many columns were low-confidence, which description you would change, and why.

| Table | Low-confidence columns | Description you would change | Why |
|---|---|---|---|
| dim_product | | | |
| dim_customer | | | |
| fact_sales | | | |

---

## Part C. Break it (10 min)

Try each attack. Record what happened and which control stopped it.

| Attack | What you typed | Result | Control that stopped it (file and function) |
|---|---|---|---|
| Ask for 1000 sample rows | `limit=1000` | | |
| SQL injection in a table name | `dim_product; DROP TABLE x` | | |
| Read a schema you should not | `schema=finance` | | |
| Read the catalog's internal table | `table=_catalog_metadata` | | |
| Call a write tool | Is there one? List the tools. | | |
| Propose a column that does not exist | `ghost_col` | | |
| Label an email column "other" | `cust_email` as `other` | | |

**Final question (write 3 to 5 sentences):** If the model were fully compromised by a malicious value in the data, what is the most it could do in this design? What would you change to make that even smaller?

---

## Hand in
1. Completed canvas (Part A)
2. Screenshot of `python -m review.approve catalog`
3. Part C table and your final answer
