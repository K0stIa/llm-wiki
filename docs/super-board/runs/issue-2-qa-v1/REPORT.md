# Issue #2 QA

PR #5 implementation reviewed at `d13fc8db87f7200d8e2723da9b32616bb539798e`. All four acceptance criteria passed synthetic checks. Frozen G2 proof remains pending in the approved local environment.

| Acceptance criterion | Unit evidence | Component evidence | End-to-end scope |
|---|---|---|---|
| Report the runtime binding | `tests/runtime/trace-v2.test.mjs:117` asserts approved defaults and explicit overrides. | Ran both TypeScript entry points with a synthetic retrieval adapter that recorded each binding. The three trace outputs matched the binding. The performance output matched all 120 captured bindings and the SHA-256 of the dummy reranker file. The input report carried different settings and a decoy digest. See `src/eval/trace_v2.ts:108`, `:174` and `src/eval/perf_v2.ts:48`, `:179`. | Native backend and device behavior need the approved G2 run. |
| Refuse malformed or mismatched proof | `tests/hypothesis/test_g2_measurement.py:95`, `:124`, `:145` and `tests/runtime/trace-v2.test.mjs:135` cover admission and validation. | Called `publish_holdout` with separate synthetic retrieval and performance reports. In either report, CPU, depth 25, token limit 513, an extra settings key, a wrong digest, and development subset all kept the writer untouched. An invalid profile version also stopped the call. The approved pair reached the writer once. Both profile loaders agreed on ten shared numeric, type, version, and boundary inputs. | No receipt was published. |
| Keep development overrides and withhold receipts | `tests/runtime/trace-v2.test.mjs:117` asserts that CPU, depth 30, and 256 tokens are available in performance development mode and refused in frozen mode. | `tests/hypothesis/test_g2_measurement.py:160` checks that matching experimental settings reach the scorer without publishing. Depth 24 against a retrieval binding of depth 30 stopped before scoring. The independent benchmark adapter observed all three experimental values. | Synthetic development CLI coverage. |
| Require new frozen proof after a profile change | `tests/hypothesis/test_verification_receipts.py:63` asserts that commit drift makes proof stale. | In a scratch Git repository, a synthetic G2 performance receipt passed for its original clean identity. Changing depth marked the profile dirty. Committing that one change kept the other identity inputs equal and made the existing proof stale. | Current gate status reports G2 evidence missing. |

## Verification

- Strict TypeScript passed. Python passed 86 tests, including the extended receipt suite, with one private-corpus case deselected. Node passed 14 tests.
- The independent proof fixture initially included untracked report files in its Git repository. Moving the proof fixture to its own directory produced the intended clean baseline and verified staleness after the profile-only commit.
- The saved GitHub review snapshot contained 10 file summaries and three inline author notes, with no replies, QA findings, or additional pages.
- Test gaps (not written). The runner binding and report comparison used a one-off synthetic adapter. The native backend, loaded model, and measured performance still require frozen G2 verification.
- Screenshots omitted because the issue changes command-line evaluation and receipt behavior.

```sh
node_modules/.bin/tsc -p tsconfig.json &&
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py tests/hypothesis/test_verification_receipts.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint' &&
node --import tsx --test tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
```
