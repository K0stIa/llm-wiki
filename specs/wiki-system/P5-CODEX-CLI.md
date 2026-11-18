# P5: Codex CLI Integration — version-checked config + child fixture

## Scope

Deliverable: verify Codex CLI v0.163.0 **configuration and capability flags**.
**No child execution is verified.** `codex exec fork --help` only proves the
CLI accepts the subcommand; it does NOT prove a child agent can read/write the
wiki or that approval/sandbox bypass is safe.

No new code beyond test harness and validation scripts. Runtime integration
remains **unverified** until an actual `codex exec fork` child is launched
and its output is captured and verified against the wiki contract.

Do NOT use `--dangerously-bypass-approvals-and-sandbox` in automated tests;
it is a documented escape hatch for externally sandboxed environments only.

## P5 deliverables

| # | Deliverable | Evidence |
|---|---|---|
| 5.1 | Version-checked configuration | `codex --version` ≥ target; config TOML parses without `--strict-config` errors |
| 5.2 | Project-local connection (`--cd` / `--add-dir` / `--worktree`) | `codex exec -c <prompt>` into a worktree; child inherits repo context |
| 5.3 | Child mechanism (`codex exec fork`) | Fork a parent thread; child receives the parent's conversation context |
| 5.4 | Approval modes | `default_tools_approval_mode = "prompt"` verified in config; `--dangerously-bypass-approvals-and-sandbox` documented as the escape hatch |
| 5.5 | `codex doctor` denied-read rules | `denied-read rules: 0` confirmed; `denied-read glob rules: 0` confirmed |

## G5 gate (config-only, child runtime unverified)

| Item | Status |
|---|---|
| Version ≥ 0.163.0 | ✓ |
| Config parses (`--strict-config`) | ✓ |
| `--cd` / `--add-dir` / `--worktree` flags present | ✓ |
| `codex exec fork` subcommand exists | ✓ (help only) |
| Approval mode = `prompt` per MCP server | ✓ |
| `denied-read rules: 0` | ✓ |
| **Actual child execution** | **UNVERIFIED** |
| **Actual `codex exec fork` success** | **UNVERIFIED** |
| **Actual `--cd` runtime** | **UNVERIFIED** |

`codex exec fork --help` proving the flag exists ≠ child gate. Fork help
is not evidence that a child agent can read the wiki, write pages, or that
the fork prompt is delivered correctly. This gap must be closed before G5 passes.

## Dependencies

- Codex CLI v0.163.0 (installed at `/home/kos/.local/bin/codex`)
- Config at `~/.codex/config.toml`
- `codex-app-tools` MCP plugin with `create_thread`, `send_message_to_thread`,
  `fork_thread`, `handoff_thread`, `delete_thread`
- `codex doctor` with `denied-read rules: 0`

## Notes

- `default_tools_approval_mode = "prompt"` means each tool call requires a
  confirmation prompt. For automated testing, `--dangerously-bypass-approvals-and-sandbox`
  is the documented escape hatch (DANGEROUS — only for externally sandboxed envs).
- The `codex_app` MCP tools (`fork_thread`, `handoff_thread`) are the **MCP-level**
  child mechanism, separate from `codex exec fork`.
- No execpolicy `.rules` files exist on this system (verified in P4).

## Implementation notes

- 5.1: parse config.toml with Python `tomllib`; assert version ≥ target
- 5.2: `codex exec --cd /path --add-dir /other -c "readme check"` — verify it runs
- 5.3: `codex exec fork <id>` → capture new thread id from output
- 5.4: read `config.toml` for `default_tools_approval_mode`; document `--dangerously-bypass-approvals-and-sandbox`
- 5.5: `codex doctor | grep "denied-read"` → assert count == 0
