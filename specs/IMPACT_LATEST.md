# P3/P4 bridge and backup/restore repair

## Target
`src/authority/bridge.ts`, legacy service handlers and operator-only backup/restore in `src/mcp/transport.ts`.

## Dependents
- Legacy `createMCPServer` / `createWikiService` and `src/pi/pi-integration.ts` use bridge page/propose/decide/operation results.
- MCP stdio uses the shared Python authority dispatcher. Epoch-bound review validation must cover both entrypoints.
- P2 retrieval binds generations and `atLeast` to authority/project/epoch. Restore invalidates old generations and enqueues bootstrap work without changing retained revisions. Old barriers return `stale-epoch` even after equal numeric sequences.
- Pending discovery now carries an epoch-bound review digest and scoped keyset cursor with a scan cutoff. Payload digests stay unchanged. Curator decisions require the reviewed token, not the proposal receipt's payload digest.
- New revision/source/proposal/generated-operation identities include the epoch. Idempotent receipt lookup verifies project, principal and the complete original request, including every source, rather than acknowledging changed text under a retained key.
- Backup/restore have no functioning runtime caller or regression today. The current backup assumes a Python connection object in JavaScript; restore calls an undefined helper after copying files.

## Affected stories
DELIVERY P3 service boundary/backup/restore and P4 actual TypeScript-to-Python boundary. P2 freshness is a restore dependent. DELIVERY.md remains byte-identical.

## Coverage and gaps
Existing bridge checks mostly run Python directly or inspect source. New tests must invoke actual TypeScript exports and subprocesses for full-body create/read/propose/review/decide, scope errors, missing/failed/invalid subprocess responses and clean temporary-file disposal.
Backup tests must invoke SQLite backup during committed WAL writes, verify a versioned hash manifest, restore into a clean temporary instance, rotate every project epoch, retain exact historical citations and pending proposal bodies, reject stale review tokens and old freshness barriers, and rebuild from restored authority. Corrupt/missing/mismatched backups and occupied destinations must fail without replacing accepted data.

## Risk: High
Shared result contracts and recovery paths affect durable knowledge. No fabricated success fallback, unchecked cast, diagnostic suppression or live-database file copy is acceptable.

## Recommended action
Add real failing regressions first. Use argument-vector subprocesses and validated operation-specific JSON results. Keep operator recovery outside model-facing MCP tools. Verify the expanded strict TypeScript set and full suite from a hashed isolated repository. No production mutation, new grant/download, release or independent G8 claim.
