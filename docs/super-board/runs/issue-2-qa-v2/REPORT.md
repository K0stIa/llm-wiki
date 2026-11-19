# Issue #2 QA v2

Synthetic QA passed on draft PR #5 at `4b9f06d99099593fbacdac34796520fa2c21e7c0`. Frozen G2 proof remains pending in the approved local environment. The local gate checker reported G2 evidence missing.

| Acceptance criterion | Evidence |
|---|---|
| Record the runtime binding | The binding tests in `tests/runtime/trace-v2.test.mjs` passed. Code review confirmed that the trace records the binding used for normal and oracle ranking, and the benchmark records its own binding and hashes the model file it uses. [QA v1](../issue-2-qa-v1/REPORT.md) captured both bindings with a synthetic adapter. This pass independently confirmed that new trace runs reject both an unapproved override before workload setup and an unapproved setting in a runner output. |
| Refuse malformed or mismatched proof | The tests in `tests/hypothesis/test_g2_measurement.py` confirm that profile drift, a wrong model digest, and a malformed approved profile withhold admission. The approved report pair reaches the stub receipt writer. A JSON array or null in a performance report yields the withheld message without calling the writer. Independent probes also covered a number, string, boolean, and nonempty array. |
| Keep development overrides and withhold receipts | The existing scoring regression confirmed that matching experimental settings reach scoring without publishing and mismatched settings stop before scoring. TypeScript tests confirmed that explicit overrides are available in performance development mode and rejected in frozen mode. |
| Require new frozen proof after a profile change | The extended receipt suite passed, including clean-identity staleness checks. The profile-only commit probe is recorded in [QA v1](../issue-2-qa-v1/REPORT.md). |

Both saved trace versions displayed an intact historical profile with settings different from the current profile. The replay regression rejected a damaged output and rejected missing, malformed, or different settings in provenance or in any of `report.json`, `trace.json`, `raw.json`, and `oracle-raw.json`, even after refresh of the affected artifact digest.

The saved complete review response contained author notes and no QA findings or replies. OpenHands found one low-severity diagnostic gap. Invalid JSON syntax in a performance report raises a parser error before receipt publication. The tested valid JSON values with an invalid shape follow the withheld path.

## Verification

Locked dependency installs and strict TypeScript passed. Python passed 89 tests, with one private-corpus-dependent case deselected. Node passed 14 tests. Six additional synthetic probes passed using temporary fixtures. Native device selection, model loading, and measured performance remain outside synthetic QA.

```sh
uv sync --locked
npm ci --no-audit --no-fund
node_modules/.bin/tsc -p tsconfig.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py tests/hypothesis/test_verification_receipts.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
node --import tsx --test tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
```
