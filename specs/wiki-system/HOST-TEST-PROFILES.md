# Host test profiles (for owner review before the first run)

Status: drafted 2026-11-15, **not yet run**. Phase H needs owner approval before any of these commands execute (see [DECISIONS.md](DECISIONS.md) D1, D3).

Every profile is per invocation. Nothing is written to `~/.codex`, `~/.claude`, `~/.config/opencode` or any global setting. Each run uses:
- a disposable authority database and journal under a fresh temporary directory;
- a separate test worktree as the working directory;
- synthetic nonce facts first, then approved representative tasks.

Placeholders: `$REPO` is this repository, `$DB` the disposable authority database, `$PROJECT` the test project id, `$WT` the test worktree.

The wiki MCP server is always launched as worker, never curator:

```
node $REPO/node_modules/tsx/dist/cli.mjs $REPO/src/mcp/stdio.ts $DB $PROJECT worker
```

It exposes `wiki_page`, `wiki_read`, `wiki_recall`, `wiki_propose` and `wiki_operation`. It has no curator tools, no file or URL access, and identity and project are fixed at launch. The curator runs separately in a trusted harness (`stdio.ts ... curator`) and is never reachable from host configuration.

## Codex CLI 0.169.0

```sh
codex exec --json -s read-only -C "$WT" \
  -c 'mcp_servers.wiki.command="node"' \
  -c "mcp_servers.wiki.args=[\"$REPO/node_modules/tsx/dist/cli.mjs\",\"$REPO/src/mcp/stdio.ts\",\"$DB\",\"$PROJECT\",\"worker\"]" \
  -c 'mcp_servers.wiki.default_tools_approval_mode="approve"' \
  "<scenario prompt>"
```

What this grants and what it doesn't:
- **Grants:** `approve` auto-approves only this run's `wiki` server tools. Verified locally: `codex mcp list` accepts `approve`, `auto` and `prompt`, and rejects other values.
- **Unchanged:**
  - The shell sandbox stays `read-only`.
  - Non-interactive shell escalations are still denied.
  - Existing servers keep their own settings: `node_repl`, and `cloudflare-api` at `prompt`.
- **Open item:** ambient MCP servers still start. If they interfere (the earlier run logged a Firecrawl token error), add `-c 'mcp_servers.<name>.enabled=false'` for this run only. That key is not yet verified.

## Claude Code 2.1.325

```sh
claude -p --output-format stream-json --verbose \
  --strict-mcp-config \
  --mcp-config "{\"mcpServers\":{\"wiki\":{\"command\":\"node\",\"args\":[\"$REPO/node_modules/tsx/dist/cli.mjs\",\"$REPO/src/mcp/stdio.ts\",\"$DB\",\"$PROJECT\",\"worker\"]}}}" \
  --agents "$REPO/src/p6/wiki-child-agent.json" \
  --allowedTools mcp__wiki__wiki_page mcp__wiki__wiki_read mcp__wiki__wiki_recall \
                 mcp__wiki__wiki_propose mcp__wiki__wiki_operation Agent \
  "<scenario prompt>"
```

- **Strict MCP config:** `--strict-mcp-config` loads only this `wiki` server, ignoring all other configured MCP servers.
- **Allowed tools:**
  - The wiki tools.
  - `Agent`, needed for the parent to launch the `wiki-child` subagent.
  - Everything else follows the existing permission settings. In print mode, anything not allowed is denied, not prompted.
- **Child agent:** the `wiki-child` definition (`src/p6/wiki-child-agent.json`) allows only the wiki tools and denies Bash, Read, Edit, Write, WebFetch, Agent and Task.
- **Coverage:** DELIVERY requires foreground and background children. Both are run with the same flags.

## OpenCode 1.19.5

Retest first (D3). Proposed run, to be finalized after a dry config load:

```sh
OPENCODE_CONFIG="$TMP/opencode-wiki-test.json" opencode run --agent build "<scenario prompt>"
```

`$TMP/opencode-wiki-test.json` would add a local `wiki` MCP server with the same worker command, and the `src/p7/wiki-child-agent.json` subagent with `mode: subagent`, wiki tools only. The model stays the configured `local-llamacpp` profile.

Not verified yet:
- whether `OPENCODE_CONFIG` merges with or replaces the user config;
- whether the `task` tool is exposed to the local model in `run` mode.

Both are checked with `opencode debug config`-style dry loads before any model call.

## What every run must record (Tier C receipt inputs)

- The raw host JSONL transcript and the exact argv.
- Host and model versions.
- The temporary database, captured through the supported backup API after the run.
- The scenario id and nonce.

A per-host normalizer and the shared scenario checker (COMPLETION-PLAN §3, Tier C) decide pass or fail from those files, never from the host's summary.
