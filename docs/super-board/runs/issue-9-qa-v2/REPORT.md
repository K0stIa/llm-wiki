# Issue #9 QA v2

Passed on the OpenHands-reviewed PR #13 head `7ed28afbdfdfb291434e1c8b9c6c5c680501c510`. The revision after QA v1 changes only trace copy timing and empty-project handling in production. It removes the Python subprocess's 120-second copy timeout and keeps the SQLite backup for an empty project set. The generation lock and lease implementation is identical to v1.

## Acceptance evidence

Reran the [v1 synthetic fixtures](../issue-9-qa-v1/REPORT.md) as an unprivileged user. The two runner tests in `tests/runtime/generation-lifecycle.test.mjs` exercise the real copy and lease paths up to workload startup.

| Criterion | Trace and performance results |
|---|---|
| Reject malformed source artifacts before measurement | Both rejected pointer traversal, invalid manifest JSON, and SQLite bytes that differed from the manifest digest. No destination pointer appeared and neither workload started. |
| Copy expected artifacts and preserve the source | Each destination contained a current pointer and one generation with the original index and manifest bytes. Extra files stayed out. Source pointer, manifest, and index bytes matched before and after copying. The authority backup contained the synthetic row. |
| Hold and release the lease | Each file copy observed one source lease. Real cleanup ran with the source generation temporarily non-current and left it intact. Both runners released the lease on success and after an injected manifest copy failure. Failure removed the partial generation and preserved the source bytes. |

Both runners failed before copying when lease-directory writes were denied. Trace also rejected a model digest mismatch even with matching trace provenance. The [saved-generation documentation](../../../../specs/wiki-system/EVAL-V2.md#saved-generations) tells operators to use a writable source run for a read-only archive so cleanup can honor the source lease.

## Timing repair

A separate Python process acquired an exclusive `fcntl.flock` on a valid synthetic generation's actual `.lock` and signaled readiness before the copy began. The real snapshot copier rejected with `generation lock timeout` after 5,008 ms while the holder was still alive, with no lease or destination. After the holder released the lock, a retry in the same Node process copied the index and released its lease. Source bytes were intact. The unchanged `locked()` implementation races acquisition against 5,000 ms and sends an unlock or cancellation request in its `finally` block. This probe was temporary.

Separately, the parameterized Python trace-copy test checks the complete subprocess call for a nonempty project set, including `check=True` and the absence of a `timeout` argument. It also checks the SQLite-only case for an empty project set. The trace call and Node copy path impose no whole-copy deadline. The real lock probe exercised lock acquisition, and the exact-call assertion verified the timeout configuration without waiting 120 seconds.

## Local verification

Reused installed dependencies after matching both package manifests and lockfiles.

```sh
node_modules/.bin/tsc -p tsconfig.json
node --import tsx --test tests/runtime/generation-lifecycle.test.mjs tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
.venv/bin/python -B -m pytest -q -p no:cacheprovider -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
```

Strict TypeScript passed. Node passed 25 tests, including 11 generation lifecycle tests, with zero skips. Python passed 87 tests, with one private-corpus case deselected.

The fixtures cover digest validation and leave SQLite structural integrity with a recomputed matching digest untested. Both runners still back up the authority before acquiring the index lease. A concurrent promotion in that existing timing window can pair the backup with a newer generation. Real workloads, models, private inputs, and runtime release gates were outside scope. The criteria are non-visual.
