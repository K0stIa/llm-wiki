# P8: Release + G8 Gate

## Scope

Deliverable: independent verification, tested rollback, sanitized artifacts,
operator runbook, SHA-bound verifier receipt. Independent from the implementer.

## P8 Deliverables

| # | Deliverable | Evidence | Status |
|---|---|---|---|
| 8.1 | Independent verification | Fresh run of all 73 hypothesis tests | ✗ |
| 8.2 | Tested rollback | `git checkout` to pre-release state works | ✗ |
| 8.3 | Sanitized artifacts | No private corpus text in artifacts | ✗ |
| 8.4 | Operator runbook | `RELEASING.md` with step-by-step deployment | ✗ |
| 8.5 | SHA-bound verifier receipt | `p8-verifier.sh` hashes all deliverables | ✗ |
| 8.6 | G8 gate: all hosts verified | P5 config✓+runtime?, P6?, P7? | ✗ |

## G8 Gate

| Gate | Status |
|---|---|
| All P0–P5 config/capability checks pass | ✓ |
| All P0–P5 runtime verified (actual child execution) | ✗ P5 unverified |
| All P6 deliverables pass | ✗ |
| All P7 deliverables pass | ✗ |
| 73/73 hypothesis tests pass | ✓ |
| Frozen corpus v1 SHA-256 manifest matches | ✓ |
| No open release blockers | ✗ |
| Operator runbook human-readable | ✗ |
| SHA-bound verifier hash recorded | ✗ |

## P8 release readiness

Not ready for P8 until:
- P5: actual `codex exec fork` child verified (not just `--help`)
- P6: actual Claude Code child verified (not just `--help`)
- P7: actual OpenCode child verified (not just `--help`)
- P5/P6/P7 runtime children produce correct wiki read/write output
- Cross-project authorization enforced on all three hosts
- `--dangerously-bypass-approvals-and-sandbox` NOT used in tests
- Operator can follow `RELEASING.md` without running code

## Notes

- P8 is the independent gate; no automated "production-ready" marking from
  document checks alone (per DELIVERY.md)
- If any P6 or P7 phase is blocked, P8 records that as a known limitation
- Release from clean sanitized history only
- G4 child mechanism unverified: documented API does not exist in
  pi-subagents v0.12.5; child execution requires live Pi session only
