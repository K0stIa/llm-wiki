# Issue #3 QA, round 1

Reviewed draft PR #6 at `49db46d31d09522a4621d6333a50c805ea1d663d` against published base `24e82db14e3a3d273eb3c795b8c05b2034db6c77`.

| Acceptance criterion | Evidence |
| --- | --- |
| Shared durable writes and compatible formats | Compared the candidate with its base. Both collectors call the same create and append helpers. Creation retains mode `0600` and parent-directory sync. Append retains checksum calculation, UTF-8 JSON plus newline, flush, and file sync in that order. Checkpoint construction and row fields are unchanged. Synthetic collection checks verify both file modes, replay row bytes and checksums, and the existing checkpoint schema. |
| Recovery and admission | Baseline retains verified rows after a torn append and refuses an altered complete row. Replay resumes without re-requesting saved rows, honors the request limit, rejects an altered row, and excludes holdout input. Synthetic endpoint stubs observe the actual request sequence. |
| Provenance | A parameterized test edits the source bytes inside each helper independently and confirms replay rejects the saved checkpoint before opening the endpoint or changing saved rows. With the source binding temporarily replaced by a constant and the direct hash assertion bypassed, both cases failed by reaching the endpoint stub. The binding and assertion were restored before the final run. |

The diff also preserves artifact paths, request policies, and gate eligibility. The saved review-thread response contains three author notes and no unresolved QA findings. The focused suite covers the high-risk cases in scope. A forced OS crash during file or directory sync was outside this isolated run. The call order was reviewed against the base.

## Verification commands

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'
node_modules/.bin/tsc -p tsconfig.json
node --import tsx --test tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs
```

The deterministic-slice test was excluded as directed for the isolated run. QA used published source and synthetic fixtures. No private corpus, real G2 evaluation, or receipts were used. Screenshots were omitted because this change affects persistence and replay only.

Results: 60 Python tests passed with one deselection, TypeScript passed, and all 14 Node tests passed.
