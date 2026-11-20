# Issue #10 QA evidence

Reviewed draft PR #14 at `6e916f8187ecca6af40d9717f75297d8d6e0c518`. All three acceptance criteria passed in synthetic Git fixtures.

| Criterion | Observed |
|---|---|
| Second edit changes identity | Two edits to `src/engine.ts` retained the same dirty path and produced different source fingerprints. Rename, executable mode and non-UTF-8 path cases passed. |
| Final provenance rejects source drift | Synthetic performance and trace workloads edited previously dirty source and were rejected before writing a report. Trace also rejected a second edit outside runtime source. QA extended the trace regression to cover both paths. |
| Clean and development compatibility | Clean identity retained the old fields and receipt key. Ignored runtime links kept the checkout clean, clean current receipts counted, dirty receipts were exploratory, and stable dirty development evidence remained usable. |

Legacy dirty retrieval and trace inputs required a fresh development run for reuse or scoring. Read-only inspection printed historical trace reports for both supported versions and retained integrity checks. Untracked, staged and committed runtime link fixtures failed closed. Unrelated external links bound the entry, and changing outside file bytes left the digest unchanged. The checkout walker exits at paths outside its root before calling the target file reader.

- Focused Python receipt, G2 measurement, answer/scoring and replay suite: **133 passed, 1 deselected**. The deselected test uses the private corpus.
- Focused Node native search queue and trace suite: **14 passed**.
- Strict TypeScript: **passed**.

The checks are non-visual. All fixtures used synthetic data and stub workloads.
