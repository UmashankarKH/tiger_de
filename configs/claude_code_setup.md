# Connect the lab server to Claude Code or Claude Desktop

## Claude Code

```bash
claude mcp add --transport stdio \
  --env PYTHONPATH=/ABSOLUTE/PATH/TO/mcp-catalog-lab \
  --env CATALOG_BACKEND=sqlite \
  cpg-catalog -- /ABSOLUTE/PATH/TO/mcp-catalog-lab/.venv/bin/python -m catalog_mcp.server

claude mcp list          # should show cpg-catalog as connected
```

Then in a Claude Code session try:

> Use the cpg-catalog tools to document cpg.fact_sales. Read glossary://cpg first, then propose metadata.

## Claude Desktop

Copy `claude_desktop_config.json` into your Claude Desktop config (Settings, Developer, Edit Config),
replace the two `/ABSOLUTE/PATH/TO/` values, and restart the app. The tools appear under the connectors menu.
You can also pick the `document_table` prompt from the prompt list.

## Rules for any config file

- Put **no secrets** in it. Config files get shared, committed and screenshotted. Use OAuth, a secret manager or an env var set outside the file.
- Use absolute paths. The host starts the server from its own working directory, not yours.
- Point it at a **read-only** identity. The approval CLI is the only thing that should ever hold a write credential.
