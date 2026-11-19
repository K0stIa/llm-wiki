# Issue #8 QA evidence

QA passed all three acceptance criteria on OpenHands-reviewed source commit `54deb81ded5f6fdafa8ab05c1711ee4b29f33c03`. OpenHands' prior invalid-subset finding was fixed. The guarded review-thread read showed eight author notes and no actionable replies.

| Acceptance criterion | Component evidence under `tests/hypothesis/` |
| --- | --- |
| Refuse malformed or mismatched consumed artifacts early | `test_eval_v2_scoring.py:364` refuses a digest mismatch and a correctly hashed JSON array before the endpoint. `test_g2_measurement.py:224` refuses mismatched or malformed reports before the workload. At line 295, a verified development report is replaced with a publishable holdout report after the first read. The receipt writer stays uncalled. A temporary in-memory change that parsed a second read made the test fail with “published an unattested report.” |
| Preserve eligibility and checkpoint resume | `test_g2_measurement.py:96,224,334` covers profile checks, development skipping publication, invalid subset refusal, and eligible holdout digests. `test_eval_v2_scoring.py:290,328` covers a timeout, torn line, and altered completed row. `test_eval_v2_replay.py:47,110,124` covers development resume, holdout refusal and damaged checkpoints. |
| Preserve saved report and checkpoint formats | `test_eval_v2_scoring.py:255,290` reads the existing provenance and round-trips the answer run. `test_eval_v2_replay.py:47` reuses the completed replay. `test_verification_receipts.py` passed all 31 tests, including receipt and gate compatibility checks. |

The component tests exercised the Python entry points with synthetic artifacts and mocked external calls. Dedicated reader unit tests were absent. Browser coverage was inapplicable to this CLI-only change. The TypeScript benchmark still checks the report and raw ranking bytes independently. The remaining coverage gap is a dedicated replacement test for the performance report at publication. The observed-profile test checks the digest passed to the writer.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
```

72 passed and the private-corpus case was deselected. TypeScript and all 14 focused Node tests passed. Installed dependencies were reused after both manifests and locks matched byte for byte. QA used no live endpoints, models or published measurement receipts.
