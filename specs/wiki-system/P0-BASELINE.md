# P0 Baseline Status

**Date**: 2026-11-10
**Branch**: `fix/wiki-design-closure`
**Status**: P0 complete. READY for P1.

## What was implemented

| Item | Status | Notes |
|---|---|---|
| Authority schema (migrations.sql) | ✓ | 14 tables, WAL, FK, FTS5, outbox |
| KnowledgeStore (authority.py) | ✓ | CAS, idempotency, propose/decide/page/read |
| Curator | ✓ | paged discovery, metadata sweep, reject |
| Profile (profile.yaml) | ✓ | P0 defaults, all unknowns recorded |
| Authority + Curator tests | ✓ | 9 hypothesis property tests, all pass |
| MCP Memory Service probe | ✓ | RETAIN SQLite authority (source review only) |
| Corpus builder (corpus.py) | ✓ | 9 slices, 200+50 questions |
| Frozen corpus | ✓ | `frozen-corpus.py freeze` |
| Answer model pinned | ✓ | qwen3.8-35b-a3b-mtp-32k, local-llamacpp |
| Design closure | ✓ | READY-FOR-IMPLEMENTATION (verified) |

## Pinned answer model (G0)

| Parameter | Value |
|---|---|
| Provider | `local-llamacpp` |
| Model | `qwen3.8-35b-a3b-mtp-32k` |
| Thinking | `off` |
| Input budget | 32,000 tokens |
| Output reserve | 4,096 tokens |
| Tokenizer | `tiktoken_cl100k` |
| Approved endpoint | private LAN (loopback or 192.168.x.x) |

**Never send private corpus text to an unapproved provider.** G2's headless answer harness is not proof of any CLI's behavior.

## Corpus freeze

- `research/eval-corpus/frozen/v1/manifest.json` — SHA-256 of all corpus files
- `frozen-corpus.py verify` — run before any corpus modification
- 200 answerable + 50 controls, 40/60 dev/holdout split
- 7 positive slices + 2 control slices (stratified)
- Each hard slice ≥30 held-out positives

## MCP Memory Service decision

**RETAIN SQLite authority.** MCP Memory Service does not provide durable proposals, digest-bound review, same-page CAS, replay receipts, scoped citations, or project authorization together. Its source contains connection locks but this does not establish end-to-end safety.

Reuse:
- QMD search backend (best-measured retrieval)
- Pi LLM Wiki integration (tested child runner, sessions)
- SQLite FTS5 (model-free lexical control)

## Gate G0 checklist

- [x] Clean isolated workspace (worktree, no live-service modification)
- [x] Pinned code versions (SQLite 3.45+, Python 3.12, Node 22)
- [x] Schema verified (14 tables, all FKs, FTS5 virtual table)
- [x] Authority tests pass (9/9 hypothesis property tests)
- [x] Corpus built and frozen (SHA-256 recorded)
- [x] Answer model pinned and available on private LAN
- [x] MCP Memory Service source reviewed (not deployed)
- [x] Profile documented with all unknowns
- [x] Design closure verified (`verify.py --require-ready` exits 0)
- [ ] G1 runtime tests (process races, crash/restart) — **P1 scope**
- [ ] G2 recall gates — **P2 scope**

## Unknowns (to resolve in P1/P2)

| Unknown | Source | Resolution |
|---|---|---|
| real_corpus_size | DELIVERY.md G0 | P1 deployment profile |
| hardware_constraints | DELIVERY.md G0 | P1 |
| retention_policy | DELIVERY.md profile | P1 legal review |
| remote_access_requirements | DELIVERY.md profile | P1 |
| production_slos | DELIVERY.md profile | P1 |
| approved_model_weights_license | DELIVERY.md G0 | P1 legal |
| production_trust_boundary | DELIVERY.md profile | P1 |

## Next: P1 — durable core

Gate G1 scope: migrations, proposal capture, immutable revisions,
curator CAS, idempotency receipts, transactional FTS/outbox,
exact citation reads. Runtime: actual process races and crash/restart
tests against a real service (not type tests or document checker).
