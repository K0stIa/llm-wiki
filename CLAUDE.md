# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Three loosely related parts:

1. **`research/`**: a measured comparison of shared-wiki options for Pi sessions and child agents. It includes QMD vector retrieval, Pi LLM Wiki and MCP Memory Service. Results are in `research/README.md` and `research/results/*.json`.
2. **`specs/wiki-system/`**: the chosen production design. A transactional SQLite knowledge authority produces Markdown as a generated export, and QMD provides retrieval. `contract.d.ts` holds the type contract, `ARCHITECTURE.md` describes ownership and failure behavior, and `DELIVERY.md` defines phases P0–P8, gates G0–G8 and hard execution budgets.
3. **`src/` + `tests/`**: a prototype implementation of that design (phases P1–P4 plus partial P5–P8). **It is not a production deployment.** `src/p8/RELEASING.md` records release status as *blocked*.

The original checkout owns host access tools. This snapshot omits them.

## Hard constraints

- **Source publication.** The original checkout’s Git history must never be pushed or published. This checkout is a source-only snapshot with independent history. Keep publication and branch pushes disabled until the owner approves this snapshot and its destination. The private corpus, access files, credentials and raw verification evidence stay outside the delivery checkout.
- **Execution budget.** Check [owner decision D1](specs/wiki-system/DECISIONS.md#d1-execution-budget-per-phase) and the limits in [DELIVERY.md](specs/wiki-system/DELIVERY.md#execution-limits) before running phase verification or experiments. Phase E (evaluation set) and Phase P (retrieval and answers on the approved local endpoint) have owner-approved budgets. Host verification and independent G8 review require owner approval at phase start. Production isolation is deferred. Record failed attempts and count retries toward the budget.
- Do not mark anything production-ready from document checks or passing regressions. Only the runtime gates G0–G8 in `DELIVERY.md` count, and G8 must be an independent review.
- Do not revive the deleted custom wiki. Do not expose direct multi-writer capture tools. All mutations go through the authority's proposal → review → publish path.
- Keep generated indexes, model weights and raw sessions in the ignored `.cache/` directory. Evidence from verification runs goes in `.verification/` (untracked).
- Host rollout order is fixed: Pi → Codex CLI → Claude Code → OpenCode. A blocked host blocks the next one.

## Commands

Dependencies are locked. Python uses `pyproject.toml` + `uv.lock`, installed into the repo-local `.venv/`. Node uses exact registry versions in `package-lock.json`. Install exactly from the locks:

```sh
uv sync --locked
npm ci
```

Tests are split into tiers by pytest marker. Tier A is unmarked: no model, no network, deterministic. Tier B is `tier_b` and needs the pinned embedding GGUF. Tier C is `tier_c` and needs installed agent-host binaries and configs. Hypothesis loads the `ci` profile from `tests/hypothesis/conftest.py` by default: fixed examples, no example database, no deadlines. `HYPOTHESIS_PROFILE=explore` draws random examples for bug hunting.

```sh
# Tier A, run twice; writes a receipt and prints gate status
scripts/verify-core

# Individual tests
.venv/bin/python -m pytest -m "not tier_b and not tier_c" -q          # Tier A Python
.venv/bin/python -m pytest tests/hypothesis/test_g1_runtime.py -v      # one file
.venv/bin/python -m pytest tests/hypothesis/test_authority.py::test_cas_exactly_one_wins -v
node --import tsx --test tests/runtime/*.test.mjs                      # needs the tsx loader; no directory arg on Node 22
node --import tsx --test tests/runtime/authority-async.test.mjs

# Tier B (refuses rather than skips if the model is absent or unapproved)
WIKI_TEST_CACHED_MODEL=.cache/comparison/model-cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf \
  .venv/bin/python src/verification/run_tier.py --tier b

# Strict TypeScript check against pinned Pi 1.5.0 types (also part of Tier A)
node_modules/.bin/tsc -p tsconfig.json

# Gate status from receipts only (never runs tests)
python3 src/verification/check_gates.py

# Design integrity checks (no models or network)
python3 specs/wiki-system/verify.py
python3 specs/wiki-system/verify.py --require-ready
python3 -m unittest discover -s specs/wiki-system/tests -p 'test_*.py' -v

# Research evidence checks (no models or network)
python3 -m unittest discover -s research/tests -v

# Legacy release self-check (pre-receipt; always exits 2 until hosts are evidenced)
python3 src/p8/verify.py
```

### Evidence model

`src/verification/` holds the evidence tooling.

- `run_tier.py` first checks that `.venv` and `node_modules` match the locks. It then runs a tier and writes a receipt to `.verification/receipts/`. The receipt holds:
  - commit,
  - lock, corpus and `gates.json` hashes,
  - runtime versions,
  - model hash (Tier B),
  - per-test outcomes,
  - whether repeated runs gave identical outcomes.
- `specs/wiki-system/gates.json` maps every DELIVERY gate requirement to the tests that check it. A requirement with no test yet has an empty list and reports MISSING.
- `check_gates.py` reports PASS, FAIL, MISSING, STALE or EXPLORATORY for each requirement:
  - Only receipts from a **clean commit** whose identity matches the current checkout count.
  - Dirty-tree runs are EXPLORATORY.
  - Changing code, a lock file, the corpus or the runtime makes old receipts STALE.
- When adding a test file, map it in `gates.json`. `test_verification_receipts.py` fails if a test file is unmapped, a selector doesn't resolve, or a check's tier disagrees with the test's marker.

Don't write evidence as prose in `.verification/EVIDENCE.md`. A gate passes only through a receipt.

`specs/wiki-system/VERIFICATION.md` has the strict TypeScript contract check (`tests/contract.test.ts`), which uses a tsc under `.cache/architecture/typecheck/`. `research/README.md` has the commands to rerun the research experiments (`run-*.mjs`, `run-live.py`, `score.py`). Those reruns make live model and network calls.

## Implementation architecture

Python owns the authoritative state. TypeScript owns retrieval and host transport. They communicate over JSON-RPC subprocess bridges.

- **`src/authority/`**: the knowledge authority. `authority.py` implements the `Knowledge`/`Curator` interfaces from `contract.d.ts` on SQLite, with WAL, `synchronous=FULL`, foreign keys and `BEGIN IMMEDIATE` for page-head CAS. The schema is in `migrations.sql`. Key rules from ARCHITECTURE.md that the code enforces:
  - Idempotency keys are scoped per (project, principal, key) and bound to a request digest. Reusing a key with a different payload returns `key-reuse`.
  - Proposals move pending → blocked/decided. A conflict is terminal. A rebase is a new proposal.
  - Publish attests a `ReviewDigest`, which covers the full base, the proposed body and the cited evidence.
  - A restore creates a fresh epoch, and old `atLeast` values return `stale-epoch`.
  - `Citation.hash` is SHA-256 of the entire stored body.

  Also in this directory: `bridge_rpc.py`/`bridge.ts` (TS ↔ Python bridge), `recovery.py` (backup/restore/epoch) and `retrieval.py` (FTS5 side).
- **`src/retrieval/`** implements hybrid retrieval in TypeScript. `qmd-integration.ts` and `build-index.ts` index each project generation with page titles in the QMD embedding input. `index.ts` fuses lexical and vector ranks, prioritizes chunks with exact identifiers unique to one project object, and protects the top two fused objects when the configured reranker reorders candidates. If the reranker is busy, recall uses the fused order. Citations come from the authority. `async-authority.ts` provides a bounded pool of authority subprocesses with deadlines.
- **`src/eval/`** contains the v2 corpus builder, ranking, tracing and scoring tools. Start with the [evaluation workflow](specs/wiki-system/EVAL-V2.md) and the [frozen v2 manifest](research/eval-corpus/frozen/v2/manifest.json). Use the development split for tuning and preserve the held-out split for acceptance.
- **`src/mcp/`**: the service boundary.
  - `stdio.ts`/`protocol-stdio.ts`/`transport.ts` form the MCP server, with project/role binding fixed at launch and tool allowlists. A worker cannot gain curator authority through input fields.
  - `authority_rpc.py` is the Python side.
  - `host_journal.py` persists the idempotency key and request *before* sending, so a lost reply can be resumed (see `HOST-JOURNAL.md`).
  - `journal_rpc.py` is the trusted adapter entry point. The Pi extension uses it when `WIKI_JOURNAL` is set: proposals are keyed by Pi session id + `toolCallId`, recovery runs on `session_start`, and the MCP server starts in `journaled` mode without `wiki_propose`.
- **Crash testing**: `src/authority/faults.py` defines named crash points. `WIKI_TEST_FAULT_POINT=<name>` or `<name>:<rpc tool>` makes the process `os._exit(97)` there. New points must be registered in `POINTS`, and a test checks each is placed exactly once. The variable is launcher environment, never request data.
  - `worker_service.py` + `sandbox_worker.py` form an experimental bubblewrap worker boundary (see `WORKER-BOUNDARY.md`). It is not a production isolation guarantee.
- **`src/pi/`**: Pi integration (P4). It provides a project-local connection, answering instructions and child-agent tool access.
- **`src/p6/`, `src/p7/`**: Claude Code and OpenCode child-agent configs and validators. **`src/p8/`**: the release verifier and sanitizer.

Test names map to gates and phases. `test_g1_*` covers durability/CAS/crash-restart with real multi-process races. `test_g2_*` covers recall. `test_g3_*` covers adversarial and security cases. `test_g4_*`/`test_p4_*` cover Pi parent/child. `test_p5`–`test_p7` cover Codex/Claude Code/OpenCode. `test_p8_*` covers the verifier and rollback. Fixtures in `tests/hypothesis/conftest.py` create a temporary WAL SQLite database for each test. `tests/runtime/*.mjs` exercises the TS bridge, MCP protocol output and generation lifecycle against real subprocesses.

## Status documents

Check these before you claim progress:

- Run `python3 src/verification/check_gates.py` for the current checkout's receipt-backed gate status. Exit code 2 means gate evidence is incomplete.
- See [RELEASING.md](src/p8/RELEASING.md) for release blockers and historical evidence, including the earlier 156-test regression run. Local notes in `.verification/EVIDENCE.md` provide historical context when present.
- `specs/wiki-system/WORKFLOW.md` and `OPUS_FIXES.md`: design history.
- Reports under `specs/wiki-system/arena/` are immutable history. Do not edit them.
