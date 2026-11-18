# P7: OpenCode Integration (v1.19.3)

## P7 Scope

Deliverable: OpenCode installed-schema validation + native-child fixture.
Same contract as G5 through the **real** OpenCode child.

## P7 Deliverables

| # | Deliverable | Evidence |
|---|---|---|
| 7.1 | Version 1.19.3 at `/home/kos/.opencode/bin/opencode` | `opencode -v` → 1.19.3 |
| 7.2 | Installed-schema validation | Config at `opencode providers` / `opencode plugin` |
| 7.3 | `--agent` + `--prompt` child definition | JSON agent with wiki read/propose |
| 7.4 | `opencode agent create --mode subagent` | Subagent tool set (bash/read/edit/grep) |
| 7.5 | `--fork` + `--session` child mechanism | Fork parent → new session → child reads wiki |
| 7.6 | `--auto` escape hatch documented | NOT used in automated tests |
| 7.7 | `--pure` agent isolation | Child without plugins reads wiki correctly |
| 7.8 | G7 gate | Same contract through real OpenCode children |

## G7 Gate

| Item | Status |
|---|---|
| Version 1.19.3 | ✓ (confirmed at `/home/kos/.opencode/bin/opencode`) |
| `opencode -v` = 1.19.3 | ✓ |
| `--help` schema matches 1.19.3 docs | ✓ (checked) |
| `--fork` flag exists | ✓ (confirmed) |
| `--agent` flag exists | ✓ (confirmed) |
| `opencode agent create --mode subagent` exists | ✓ (confirmed) |
| **Actual child reads wiki** | **UNVERIFIED** |
| **Actual child proposes page** | **UNVERIFIED** |
| **Actual child approved** | **UNVERIFIED** |
| `opencode run` captures output | ? |
| Cross-project read fails | ? |
| Unauthorized child publication fails | ? |

`opencode --help | grep --fork` proving the flag exists ≠ child gate.
Fork help is not evidence that a child agent can read/write the wiki.

Do NOT use `--auto` in automated tests. It is documented as "dangerous".

## Implementation plan

1. Validate version: `opencode -v` → 1.19.3
2. Read `opencode providers` config (credential model)
3. Create subagent: `opencode agent create --mode subagent --path ... --description "wiki reader" --permissions bash,read,grep`
4. Run child: `opencode --fork --agent wiki-reader --prompt "read wiki page X"`
5. Verify child can propose and read a page
6. Test unauthorized cross-project access
7. Save receipts (exit codes, captured output, file modifications)

## Notes

- OpenCode config: `opencode providers` (not TOML), `opencode plugin` for extensions
- Child mechanism: `opencode agent create --mode subagent` (native) or `--fork` (session fork)
- `--auto` is the escape hatch (DANGEROUS — auto-approve permissions)
- G7: same contract as G5 through real children
