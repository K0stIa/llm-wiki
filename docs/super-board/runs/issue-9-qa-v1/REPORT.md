# Issue #9 QA

Verified the implementation at `92dd811a37e09dc2e0b9493e000c19fe4fd88e88` (PR #13). QA adds regression coverage and this report.

| Acceptance criterion | Observed in trace reuse and performance |
|---|---|
| Reject malformed source artifacts before measurement | Each runner rejected a traversal-shaped pointer, malformed manifest JSON and a modified SQLite index whose digest differed from the manifest. No generation pointer was published and neither workload started. |
| Copy only the expected artifacts and preserve the source | The destination held one generation with the exact index and manifest bytes and a current pointer. An unrelated source file stayed out of the destination. The source index, manifest and pointer retained their original bytes. The authority SQLite backup contained the fixture row. |
| Protect the source through copying and release the lease | Both copy operations observed one source lease over each file and ran the real generation cleanup with the source generation temporarily non-current. It survived. Both runners released the lease on success and after an injected second-file copy error. On failure the partial destination generation was removed and the source bytes stayed intact. |

Denying writes to the lease directory as an unprivileged user stopped both runners before copying and told operators to grant source index write access or use a writable saved run. Trace also refused a valid generation whose model digest differed from the requested digest, even with matching trace provenance. [Saved generations](../../../../specs/wiki-system/EVAL-V2.md#saved-generations) explains how to use an archived run from a writable location. The tests use the real on-source lease throughout.

Run from the repository root with lock-matched dependencies.

```sh
node_modules/.bin/tsc -p tsconfig.json
node --import tsx --test tests/runtime/generation-lifecycle.test.mjs tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
.venv/bin/python -B -m pytest -q -p no:cacheprovider -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
```

Strict TypeScript passed. Node passed 25 tests, including 11 generation lifecycle tests. Python passed 85 tests with the private-corpus case deselected.

The fixtures verify index integrity against its manifest, not SQLite integrity for arbitrary bytes with a newly computed matching digest. Both runners still back up the authority before acquiring the index lease. The pre-existing timing window can pair that backup with a later index generation if a publisher promotes an index between the two operations. This run tested the index copy boundary and did not test coherent authority and index capture across that window. Real workloads, models and private inputs were outside QA scope. These non-visual criteria have no screenshots and provide no runtime release-gate evidence.
