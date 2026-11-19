# Issue #8 QA v2

Pass for all three acceptance criteria at OpenHands-reviewed source `c01ad492acc0575b0ae9f374a55c4b10789e83c9`. This report supersedes v1. Synthetic CLI fixtures only, with no screenshots or runtime gate receipts.

| Criterion | Synthetic evidence |
|---|---|
| Altered or malformed inputs refuse before downstream work | `test_answer_resume_rejects_unverified_inputs_before_network`; `test_development_performance_checks_retrieval_profile_before_scoring` with separate digest and shape diagnostics; `test_receipt_rejects_report_replaced_between_parse_and_hash`. |
| Eligibility and checkpoint resume | `test_receipt_requires_valid_retrieval_subset`, `test_performance_receipt_checks_observed_profile`, `test_holdout_or_changed_authority_cannot_reach_endpoint` and `test_answer_collection_resumes_after_timeout_and_torn_line`. |
| Existing report and checkpoint formats | `test_answer_run_round_trip_uses_only_supplied_passages` and `test_replay_pairs_exact_authority_and_independent_controls_and_resumes`. The receipt suite exercises the existing writer signature and serialized format. |

All three prior production findings are fixed. Missing, malformed or unsupported subsets refuse publication, development skips it, and approved holdout passes the verified digest to the writer. Checkout identity and resume cleanliness precede report reads. Report eligibility precedes raw-ranking reads. The checkout, report-diagnostic and missing-ranking tests passed all 13 cases with both the base answer reader (`7c38607270a744d20968d3ccee2aa3687e206ecb`) and the reviewed reader.

The stale-digest fixture uses a valid report object reserialized after recording its hash. The array fixture records the array's own hash and asserts the malformed-artifacts diagnostic. Removing the digest comparison temporarily made both digest cases fail with `workload started`. Temporarily parsing a second read made the report-replacement case fail with `published an unattested report`. Production source was restored and matched the reviewed commit.

Verification with matching Python and Node lockfiles: 116 Python tests passed, one private-corpus replay case deselected, 14 Node tests passed and strict TypeScript passed. A dedicated performance-report replacement test at publication remains a coverage gap. Scoring-to-publication attestation is outside issue #8.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py tests/hypothesis/test_verification_receipts.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
node_modules/.bin/tsc -p tsconfig.json
node --import tsx --test tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
```
