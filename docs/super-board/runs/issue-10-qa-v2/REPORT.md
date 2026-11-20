# Issue #10 QA v2

PR #14 code verified at `d61f0588156bd975e537707464a4f1a88adfb6ed`.

- AC1 pass. Two edits to the same runtime source left Git's dirty path list equal and changed the fingerprint.
- AC2 pass. A synthetic performance workload edited the already-dirty source. The final provenance check rejected the result with zero scoring calls.
- AC3 pass. Clean identity kept its existing shape and an in-memory synthetic receipt passed. The dirty equivalent stayed exploratory. Stable dirty development performance reached scoring.
- Saved dirty evidence with a missing or malformed fingerprint required a fresh development run. A matching provenance-file digest did not allow answer scoring or overwrite its report.
- Git ignored links left identity stable. Untracked, staged and committed runtime links failed closed. Checked executable-bit changes with both Git filemode settings and replacement of a source directory by a file or link.
- Confined pinned links matched filesystem checksums, including chained and absolute targets. Directory-required file targets returned `MISSING`. An escaping link was rejected.
- OpenHands disposition matched the issue contract. The legacy dirty evidence finding is covered by the fresh-run rule. The runtime-link restriction is intentional, with confined pinned inputs tested separately.
- Focused verification passed: 140 Python tests, 14 Node tests and strict TypeScript. The private-corpus case was deselected.

Synthetic Git fixtures only. Evidence is non-visual. Trace work is tracked in #15.
