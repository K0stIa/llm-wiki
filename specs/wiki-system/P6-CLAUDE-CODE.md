# P6: Claude Code Integration

## P6 Scope

Deliverable: Claude Code 2.1.310 configuration, foreground/background child
policy, and child fixture. Same contract as G5 through the **real** host.

## P6 Deliverables

| # | Deliverable | Evidence |
|---|---|---|
| 6.1 | Installed version validated | `claude --version` → 2.1.310 |
| 6.2 | Config file (Claude Code's format, not Codex's) | `claude --settings` or config dir |
| 6.3 | `--agents` custom agent definition | JSON agent with wiki read/propose tools |
| 6.4 | `--add-dir` + `--allowed-tools` | Project-local + wiki path in allowlist |
| 6.5 | `--fork-session` child mechanism | Fork parent → new session → child reads wiki |
| 6.6 | Foreground/background child policy | `--agent` vs `claude agents` listing |
| 6.7 | `--print` non-interactive child | Captures child output for verification |
| 6.8 | G6 gate | Same contract through real Claude Code children |

## G6 Gate

| Item | Status |
|---|---|
| Version 2.1.310 | ? |
| Config file structure | ? |
| Custom `--agents` JSON loads | ? |
| `--add-dir` accepts wiki path | ? |
| `--allowed-tools` restricts child tools | ? |
| `--fork-session` creates new session | ? (help only) |
| **Actual child reads wiki** | **UNVERIFIED** |
| **Actual child proposes page** | **UNVERIFIED** |
| **Actual child approved** | **UNVERIFIED** |
| `claude --print` captures output | ? |
| Cross-project read fails | ? |
| Unauthorized child publication fails | ? |

`claude --help | grep --fork-session` proving the flag exists ≠ child gate.
Fork help is not evidence that a child agent can read/write the wiki.

Do NOT use `--allow-dangerously-skip-permissions` in automated tests.

## Implementation plan

1. Read Claude Code config (JSON schema at `claude --settings`)
2. Write a `--agents` JSON file with wiki child agent
3. Test `claude --agents wiki.json --add-dir /path/to/wiki --allowed-tools Bash,Echo --fork-session -p "read wiki"`
4. Verify child can propose and read a page
5. Test unauthorized cross-project access
6. Save receipts (exit codes, captured output, file modifications)

## Notes

- Claude Code uses JSON config, not TOML (unlike Codex CLI)
- Child mechanism: `--fork-session` (new session) or `claude agents` (custom agent)
- `--allow-dangerously-skip-permissions` is the escape hatch (DANGEROUS)
- G6: same contract as G5 through real children
