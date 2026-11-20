# Issue #15 QA

Independent QA passed all four acceptance criteria for draft PR #16 at OpenHands-reviewed commit `a243760d80242204c845ffef1a46828c235a4047`. The base was `b3ac9b8`.

| Criterion | Evidence |
|---|---|
| Reject further edits before reporting | `test_eval_v2_scoring.py:26` ran trace with stubbed workload results in two real Git checkouts. A second edit to already-dirty `src/engine.ts` or `note.txt` stopped the run before either report or provenance was written. The non-source edit preserved the shared identity, exercising the broader digest. |
| Confine checkout reads | `test_verification_receipts.py:302` covered untracked, staged and committed runtime links. The test at line 389 checked confined bytes and external links. An independent Git fixture guarded descriptor opens for two external targets. Target byte changes preserved the digest, and changing the relative link to an absolute link changed it. |
| Preserve inspection and enforce reuse eligibility | `test_eval_v2_scoring.py:87` and an independent v1/v2 fixture exercised saved report inspection. Missing, boolean and uppercase dirty fingerprints warned on inspection and refused reuse before any SQLite connection or destination write. Snapshot comparison showed all source files retained their bytes. Both clean formats and a valid lowercase dirty fingerprint successfully backed up a real SQLite row. |
| Run synthetic checks | 146 focused Python tests passed with one private-corpus fixture deselected. All 14 focused Node tests and strict TypeScript passed. |

The diff leaves `src/eval/copy-generation.ts`, the SQLite backup block and the leased copy invocation unchanged. The test at `test_eval_v2_scoring.py:116` confirmed backup contents before the copy invocation. No UI is affected. QA used no real model, live workload, private corpus or published verification receipt.

The independent historical fixture initially used the wrong run path and directory mode. After aligning both with the CLI's private run-directory contract, the probe passed.
