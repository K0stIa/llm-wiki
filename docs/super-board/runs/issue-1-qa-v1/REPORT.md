# Issue #1 QA, round 1

Tested `bb88503d45c7dc8680fe2e0d5290942684aa5fa3` using published source and synthetic fixtures.

| Acceptance criterion | Result | Evidence |
| --- | --- | --- |
| Separate millisecond observations for verification, reader setup, queue wait and search | Pass | `tests/runtime/authority-recall-lifetime.test.mjs:176` checks ordered finite stage timings on cold and warm recalls. Lines 192–258 check rejection and expiry, including a controlled 100,000 ms digest and no sample for work that never starts. |
| Equivalent recall and citations, single native admission, deadlines, generation pins and integrity checks | Pass | The same test compares full recall results with the observer off at line 210, verifies the citation hash at line 185, and checks integrity failures and retained leases at lines 198–245. Queue regressions cover admission, active expiry and exclusive barriers in `tests/runtime/native-search-queue.test.mjs:89`. Model regressions verify a fresh digest on every call. |
| Strict TypeScript and focused offline tests | Pass | Locked dependency installs completed, strict TypeScript exited 0, Python passed 43 tests with one private-corpus case deselected, and Node passed 24 tests. |

```sh
uv sync --locked
npm ci --no-audit --no-fund
node_modules/.bin/tsc -p tsconfig.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
node --import tsx --test tests/runtime/{authority-recall-lifetime,generation-lifecycle,model-integrity,native-search-queue,trace-v2}.test.mjs
```

The first TypeScript invocation started before npm linked its binaries and exited 127. After the locked install completed, the full verification sequence passed.

The prior review's two findings are fixed. Reader callbacks flush after setup settles, and test teardown restores the process bindings. The follow-up concern about the retired `vector.setup` key has no in-tree consumer. The serial report discovers stage names from observations and the performance report reads `vector.queue`.

Test gap: The fixture does not explicitly swap observers while a native operation is pending. Static review confirmed the dispatch captures its observer before scheduling, and the expiry test confirms settling work is reported once. UI coverage is inapplicable to these runtime changes. Real G2 and release evidence are outside this QA run.
