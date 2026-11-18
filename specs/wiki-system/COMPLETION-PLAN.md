# Completion plan

Status: proposed, 2026-11-15. Not started. This plan describes how to take the existing prototype to a G0–G8 decision. It does not change any threshold in [DELIVERY.md](DELIVERY.md), grant execution budget, or authorize release. Where this plan and DELIVERY.md disagree, DELIVERY.md wins.

## 1. Where things stand

The implementation exists and mostly works locally. The latest recorded state, from [`.verification/EVIDENCE.md`](../../.verification/EVIDENCE.md) and `src/p8/RELEASING.md`:

- Implemented:
  - the transactional SQLite authority with CAS, idempotency receipts, 100-slot admission and metadata rejection;
  - FTS5 plus QMD hybrid retrieval with generation pinning;
  - the MCP stdio server with role and project binding;
  - backup and restore with fresh epochs;
  - an experimental bubblewrap worker boundary;
  - Pi native-child wiki calls.
- Last recorded runs: 178 Python tests and 10 Node tests passing.
- Release verifier: `src/p8/verify.py` exits **2 (INCOMPLETE)**.

The remaining gaps are mostly evidence and environment problems. Missing code is the smaller part.

| # | Blocker | Kind |
|---|---|---|
| B1 | Frozen corpus v1 cannot satisfy G2. Every question has one gold page, all documents are in one project, there are no superseded facts, the 40/60 split was derived after the fact, and no independent labels exist. | Evaluation design |
| B2 | Answers: 8/28 gold-cited (target ≥90%), measured *before* hybrid retrieval. The post-hybrid answer run was never executed. | Measured shortfall |
| B3 | Ten-reader warm recall p95 is 4.154 s (target ≤2 s). Committed-to-hybrid visibility has one observation (20.1 s), not a p95. | Measured shortfall |
| B4 | The G1 host-call journal (`src/mcp/host_journal.py`) exists but no host adapter supplies a durable call identity. `src/` has no named crash points for "kill at boundary" tests. | Missing code |
| B5 | Codex and Claude Code wiki calls were denied by their approval policies. OpenCode 1.19.3 exposed no native child launcher. | Owner decision |
| B6 | Production OS identities for worker and curator are not provisioned. The bubblewrap boundary is experimental. | Owner decision + ops |
| B7 | Verification is not deterministic or reproducible. See §2. | Process |
| B8 | Evidence is prose. The verifier cannot consume host transcripts, so G4–G7 can never pass it. | Process |
| B9 | The budget STOP in `src/p8/RELEASING.md`, and no independent G8 has run. | Process |

B7 and B8 come first. Until verification is deterministic and machine-checked, any other progress is just more prose in EVIDENCE.md.

## 2. Why current verification is not deterministic

These gaps were observed in the current tree:

1. **Unpinned property tests.** There is no pytest or Hypothesis configuration. Hypothesis draws fresh random examples on every run and keeps a local example database, so two runs exercise different inputs. Tests use wall-clock `deadline=10_000`–`15_000` ms, so a loaded machine can fail them spuriously.
2. **Timing-based concurrency.** Races, kills and visibility checks rely on sleeps and process scheduling. A pass shows that one interleaving happened, not which one.
3. **Environment that cannot be rebuilt.**
   - Python deps lived in `/tmp/hypothesis-env`, which is lost on reboot, with no lock file.
   - `package.json` uses `file:` links into `~/.pi/agent/npm/node_modules`. Those are unversioned and outside the repo.
   - `test_p7_opencode.py` hardcodes `/home/kos/.opencode/bin/opencode`.
   - The embedding GGUF is only in the ignored `.cache/`.
4. **Model-dependent outcomes mixed with logic tests.** One suite run touches pure SQLite logic, the cached embedding model and installed host binaries. A failure doesn't say which layer moved.
5. **Evidence not bound to code.** EVIDENCE.md cites manifests from temporary copies. The verifier does not check that the evidence it reads came from the commit being verified.

## 3. Target verification design

Verification has three tiers. Each tier ends in a check written in code over saved data, never a human reading prose.

### Tier A: core logic (no model, no network, bit-for-bit repeatable)

Scope: authority, CAS, idempotency, admission and rejection, state table, crash recovery, journal, authorization, backup and restore, citations, FTS, verifier logic.

- **Pinned Hypothesis.** Register a `ci` profile in `tests/hypothesis/conftest.py` with `derandomize=True`, `database=None`, `deadline=None` and `print_blob=True`. Select it with `HYPOTHESIS_PROFILE=ci`. Keep a separate `explore` profile, with random draws and a large `max_examples`, for bug hunting. Commit any failure it finds as an `@example` regression.
- **Hang guard instead of deadlines.** Use `pytest-timeout` with one generous per-test limit. A timeout is a hang, not a correctness verdict.
- **Named crash points.** Add a trusted-only fault hook to the authority and bridge, enabled by an environment variable the MCP layer never forwards. At each named boundary the process calls `os._exit(97)`. The boundaries are `before-commit`, `after-commit-before-reply`, `before-promotion`, `after-promotion`, `journal-before-send`, `journal-after-send` and `journal-after-commit`. Tests restart, retry and assert from durable state. This replaces kill-by-timer.
- **Explicit interleavings.** Concurrency tests coordinate processes with filesystem or pipe barriers, so each test forces a known schedule. Keep one uncoordinated stress test per invariant (the 8-process CAS and 96-operation tests), but treat it as stress evidence, not as the deterministic check.
- **Fixed inputs.** No `uuid4`, clock or random value in assertions. Tests compare structure, digests and counts, not generated IDs or timestamps.
- **Reproducible environment.**
  - Python: `pyproject.toml` plus a hashed lock file (`uv.lock`, or `requirements.lock` with `--require-hashes`) installed into repo-local `.venv/`. Add `.venv/` to `.gitignore`.
  - Node: replace the `file:` dependencies with exact registry versions in `package-lock.json`. If a package is not published, pack it to `vendor/<name>-<version>.tgz` and reference that file, so the lock records its integrity hash.
  - Record the Node and Python versions in the lock or manifest. The verifier refuses a mismatch.
- **One entry point.** `scripts/verify-core` installs from the locks and runs pytest Tier A plus `node --test tests/runtime/`. It writes a receipt (see §3.4).
- **Determinism check.** CI runs Tier A twice on a clean checkout and compares the normalized outcome lists: test ID, outcome and assertion digest. Any difference is a bug to fix, not a retry.

### Tier B: pinned-model measurement (repeatable inputs, scored offline)

Scope: G2 retrieval recall, citation resolution, context size, latency and answers.

- **Frozen inputs.** Freeze the corpus, questions, gold labels, split, thresholds, embedding GGUF (SHA-256 `b5ce9d77…0490d63`), answer-model profile, prompts and tokenizer bound into one `eval/frozen/v2/manifest.json`. Commit it *before* any v2 measurement. The verifier rejects results whose manifest hash differs.
- **Split from seeded hashes.** Assign each question by `sha256(seed || question_id)` within its stratum, with the seed recorded in the manifest. Anyone can recompute the split.
- **Measure, then score.**
  - Measurement runs save raw rankings, raw model outputs and timings to `eval/runs/<run-id>/`.
  - Scoring is a pure function, `score(manifest, raw) -> metrics`. It is unit-tested on fixtures and rerunnable without the model.
- **Retrieval is expected to be stable** on one machine and model file. Store the top-k IDs per question. A rerun that changes any ranking is reported, as are recall changes.
- **Answers are not bit-stable.** llama.cpp sampling is not guaranteed reproducible even at temperature 0 with a fixed seed. Pin those parameters anyway. Report counts with Wilson intervals, judge pass or fail on the frozen thresholds, and keep every raw output. A rerun is a new run, never an overwrite.
- **Performance runs** record machine ID, load, queue wait, embedding time and search time separately, so the cause of a p95 regression is visible.
- **Missing model or GGUF fails Tier B.** It never skips.

### Tier C: live hosts (unrepeatable runs, deterministic acceptance)

Scope: G4–G7 parent, child and fresh-session flows, approval modes and restart.

- Each scenario run uses a fresh **nonce**, a temporary authority database and a scenario ID.
- The host adapter saves the raw transcript JSONL, plus a database snapshot taken through the supported backup API after the run.
- A per-host **transcript normalizer** (`src/hosts/<host>/normalize.py`) maps the host's JSONL to common events: session ID, parent or child, tool name, arguments digest and result.
- A host-independent **scenario checker** asserts over the normalized events plus database rows. For example:
  - the child session is distinct from the parent;
  - the child itself called `wiki_propose` with the nonce;
  - the operation receipt exists in the database with a matching digest;
  - a curator decision exists;
  - a fresh session read the published revision hash;
  - the cross-project read was denied.

  A parent's summary text is never evidence.
- Normalizers are tested against the transcripts already in `.verification/runtime/`. That gives the existing Pi evidence a machine-checkable verdict, or shows exactly why it fails.

### Receipts and the verifier

Every tier writes `.verification/receipts/<gate>/<check>/<run-id>.json`. Each receipt records:

- `commit`, which must be a clean tree; dirty runs are marked `exploratory` and never count;
- the hashes of the lock files and frozen manifest;
- the model hashes;
- the argv and exit code;
- the start and end times;
- the hash of every input and output artifact;
- the machine-checked assertions with results.

A new `specs/wiki-system/gates.json` lists, for each gate, the required checks and the tier that produces each one. `src/p8/verify.py` changes to:

1. compute the current identity (commit, locks, manifest, models);
2. load receipts and validate them against a JSON schema;
3. classify each required check as **PASS**, **FAIL**, **MISSING** or **STALE** (identity mismatch);
4. exit 0 only if every in-scope check is PASS.

The verifier itself never calls models or hosts. EVIDENCE.md becomes a generated summary of receipts, not a source of truth.

## 4. Phases

Each phase lists its exit criteria. Iteration limits come from DELIVERY.md's execution limits. A phase that exhausts its limit stops with the blocker recorded in a receipt.

### Phase V: deterministic verification foundation (no approvals needed)

1. Lock the environments: `pyproject.toml` with a hashed lock, `.venv/`, registry or vendored Node dependencies, and a version manifest.
2. Add the Hypothesis `ci` and `explore` profiles and pytest config with a timeout. Remove per-test wall-clock deadlines.
3. Replace hardcoded host paths with discovery through `shutil.which`, overridable by environment variable. Move host-binary tests to Tier C.
4. Write the receipt schema, `gates.json` and the rewritten `src/p8/verify.py`, with its own unit tests over fixture receipts covering PASS, FAIL, MISSING, STALE and dirty.
5. Write `scripts/verify-core`.

**Progress (2026-11-15):** implemented on a dirty tree, not yet committed.

- **Locks.** `pyproject.toml` + `uv.lock` install into `.venv`. Node now uses exact registry versions, which match the previously linked `~/.pi` versions. With the registry versions, Tier A and B pass and the Node tests pass.
- **Hypothesis.** The `ci` profile is the default and all 31 per-test `deadline=` arguments are removed.
- **Markers.**
  - `tier_b`: `test_p2_hybrid_runtime.py`, plus one model test in `test_bridge_recovery_runtime.py`.
  - `tier_c`: the P5–P7 host-config tests.
- **Host path.** The OpenCode path is discovered via `OPENCODE_BIN` or `PATH`.
- **Verifier.** The receipt tooling is in `src/verification/`, and the requirement map is in [gates.json](gates.json).
- **Entry point.** `scripts/verify-core` runs Tier A twice: 171 tests, identical outcomes across both runs.
- **Results.** Tier B: 14 tests pass with the approved model.
- **Gate status.** 38 checks: 21 are mapped to tests, 17 have no test yet and report MISSING.

Deviation from step 4: the receipt verifier is new code in `src/verification/` rather than a rewrite of `src/p8/verify.py`. The legacy verifier's sanitizer and rollback functions are still exercised by `test_p8_*` and mapped under G8.

Still open in Phase V:
- commit, then the first clean-tree receipts;
- CI wiring;
- a runtime version manifest beyond what receipts record.

Exit criteria:
- Two clean-checkout Tier A runs give identical outcome lists.
- The verifier reports G1 and G3 Tier A checks as PASS from receipts and everything else as MISSING. That is the honest state, and replaces "exit 2 by design".

### Phase G1-close: crash points and host journal

1. Add the named crash points (§3 Tier A) and tests for every DELIVERY G1 kill boundary, including index promotion.
2. Define a durable host call identity for each host adapter, stored outside the model payload as HOST-JOURNAL.md requires. Wire `host_journal.Journal` into the Pi adapter first.
3. Add journal crash tests at `before-send`, `after-send` and `after-commit-before-receipt`, with replay under the same key and principal.

Exit criterion: every G1 bullet in DELIVERY.md maps to a Tier A receipt that is PASS.

**Progress (2026-11-15):**

- **Crash points.** `src/authority/faults.py` defines named crash points, optionally scoped to one RPC tool (`name:tool`), placed in the authority, the RPC entry point and the journal. `test_g1_kill_boundaries.py` covers proposal, publication and outbox acknowledgement.
- **Supervisor transition.** The authority gains `block()`, the supervisor's pending → blocked event, which is a no-op after the proposal leaves pending. `test_g1_state_table.py` covers every state-table row, stale digests, and forced and raced orderings.
- **Journal in the Pi adapter.** `wiki-journal.ts` and `journal_rpc.py` connect the Pi extension to the journal. The MCP server's `journaled` mode hides the unjournaled propose. `journal-adapter.test.mjs` covers crash recovery at four points.
- **Pinned toolchain.** Pi 1.5.0 (the installed host; the repo had pinned a stale 0.79.10), `typebox`, `typescript` and `@types/node` are now pinned. `tsconfig.json` is a Tier A step.
- **Generation swap crashes.** Three Tier B crash points in the index builder (`src/retrieval/faults.ts`): after staging, after the generation rename, after the pointer swap. `test_g1_generation_swap_kill.py` covers them. Staging directories and pointer temp files now carry the builder's pid, and `cleanupGenerations` reclaims those left by dead builders; before this, a crashed build leaked its staging directory permanently.
- **Still MISSING:** `g1.oversize-admission` (needs the G0 curator profile).
- **Still unverified, needs a live Pi run:** whether Pi's tool call ids are durable across a crash, and whether the child receives the native tool.

### Phase E: evaluation set v2 (G0)

1. Build a corpus with explicit permission to use it. It needs:
   - two or more projects with lookalike page IDs;
   - multi-page answers;
   - superseded decisions carrying state metadata;
   - child-written facts;
   - Ukrainian-to-English queries;
   - exact identifiers and paraphrases.
2. Size it from DELIVERY: at least 200 answerable questions plus 50 controls, and **at least 30 held-out positives per hard slice**. With a 60% holdout that means about 50 positives per hard slice before split, with overlaps recorded.
3. Have independent labeling of ambiguous items by a reviewer without access to the implementation or to retrieval outputs.
4. Freeze `manifest.json` and commit it before any measurement. Keep questions and gold labels outside every indexed directory and agent workspace.

Exit criterion: the frozen manifest is committed and the Tier B scorer is unit-tested on it. v1 stays as a regression fixture only.

### Phase P: G2 performance and answers

1. Instrument recall to split queue wait, embedding, vector search, FTS and citation resolution.
2. Hypothesis to test first (unverified): the 4.15 s p95 comes from per-process serialization of native QMD calls ("native calls are serialized" in EVIDENCE.md) under ten readers. Confirm or refute it from the breakdown before changing code.
3. Spend at most two retrieval configurations, as DELIVERY allows.
4. Run the post-hybrid answer measurement on frozen v2 with the pinned profile. If answers stay far below 90%, record the failure. Changing the answer model is an owner decision under DELIVERY's post-hoc rule, never a silent swap.
5. Measure visibility p95 over at least 100 timed queries, with ten readers and overlapping writes.

Exit criterion: G2 Tier B receipts exist for every G2 table row, each PASS or FAIL against frozen thresholds.

### Phase H: hosts, strictly Pi → Codex CLI → Claude Code → OpenCode

For each host:

1. Write the transcript normalizer and its tests against existing transcripts.
2. Run DELIVERY G4–G7 steps 1–6 as Tier C scenarios, including the 30 answerable and 10 negative questions per host.
3. Advance only on all-PASS.

| Host | What's needed |
|---|---|
| Pi | Close the remaining G4 steps: 150-second curator decision, restart, unauthorized child publication denial, journal recovery, question subset. |
| Codex CLI and Claude Code | An owner-approved isolated test profile that allows only the wiki MCP tools in a dedicated test project directory, with no global permission changes. |
| OpenCode | The owner decides between a version that exposes native children, a recorded blocked status, or an approved alternative scope. |

Exit criterion: every in-scope host is marked verified, blocked or untested in receipts.

### Phase S: production isolation and operations (G3 remainder)

1. Provision separate worker and service/curator OS identities.
2. Rerun G3 denial tests under the real identities.
3. Schedule backups and measure RTO.
4. Test the rollback and schema-downgrade path with preserved knowledge.

Exit criterion: G3 receipts are PASS under the real identities.

### Phase R: independent G8

1. Freeze the release commit and locks.
2. A fresh verifier session gets only the requirements, the public tools, `gates.json` and the receipt locations. It reruns Tier A, then reruns Tier B scoring and samples Tier C scenarios itself.
3. One correction cycle is allowed.

Exit criterion: the verifier receipt names the SHA and every gate's status.

## 5. Owner decisions required

| Decision | Blocks |
|---|---|
| New execution budget, superseding the STOP in `src/p8/RELEASING.md` | Every phase after V (V needs no model or host calls) |
| Corpus source and permission; who labels ambiguous items independently | E, P |
| Confirm or revise G2 thresholds *before* v2 measurement | P |
| Codex and Claude Code test-profile permission for wiki MCP tools | H beyond Pi |
| OpenCode scope | H final host |
| OS identities and backup target on the deployment machine | S |
| Clean-history publication strategy (existing history contains a credential) | Any release |

## 6. Ordering and what is safe now

Phase V is safe to start immediately. It needs no models, no hosts, no network beyond package installation, and no access changes. G1-close follows on the same terms. Phases E onward wait for the decisions in §5.
