# Shared wiki/RAG system design

Chosen design: one authenticated project knowledge service. SQLite owns evidence, reviewed revisions and durable operations. Markdown is an export. QMD is the first retrieval backend, not a mandatory permanent choice.

This package is a design and implementation contract. No production service or new host integration is deployed.

Design closure is complete: [Anthropic Opus 5.5 with high reasoning](arena/closure-review.md) returned READY-FOR-IMPLEMENTATION with no remaining must-fix findings. Strict compilation, 17 checker tests, 14 research tests, 12 negative type controls and the final readiness gate pass. [The source-bound receipt](arena/closure-review.json) binds the six decision-critical files. [The ledger](OPUS_FIXES.md) records the corrections and four nonblocking follow-ups. This is implementation readiness, not production certification. Earlier reports remain immutable history.

- [Architecture and usage](ARCHITECTURE.md): authority, APIs, retrieval, concurrency, security and reuse boundaries.
- [Type contract](contract.d.ts): domain types and intended signatures, not executable implementation.
- [Delivery and acceptance](DELIVERY.md): bounded prototype, measurable gates, final independent agent and Pi -> Codex CLI -> Claude Code -> OpenCode rollout.
- [Rationale and candidate comparison](RATIONALE.md): why database authority won and what was reused or rejected.
- [Grounding](GROUNDING.md): traced existing systems and evidence limits.
- [Workflow status](WORKFLOW.md) and [source/analysis provenance](provenance.json).
- [Design verification](VERIFICATION.md): checks actually run and checks still unrun.

The installed Pi Wiki already includes MCP and QMD integration code. Reuse those components where compatible. Do not revive the deleted custom wiki or expose unsafe direct multi-writer capture tools.

Next implementation step: P0, then the transactional proposal/review/restart slice. Production suitability depends on real-corpus and actual-host tests, not these documents.

```sh
python3 specs/wiki-system/verify.py
python3 specs/wiki-system/verify.py --require-ready
```

These commands check design integrity and, with `--require-ready`, the latest source-bound review. They do not pass runtime gates G0-G8. Strict TypeScript contract tests and checker tests are described in [VERIFICATION.md](VERIFICATION.md).

Do not publish this repository's existing history. It contains a credential from earlier work. Preserve unrelated `access/` files and running services.
