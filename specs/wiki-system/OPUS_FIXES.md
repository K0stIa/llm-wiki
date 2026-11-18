# Opus findings: confirmation, correction and proof

Scope: fix the design and public contract, not build or deploy the proposed service. Preserve the [original Opus report](arena/opus-5-5-review.md) unchanged.

Current request: complete one consolidated repair/verification change set. Working budget: at most two repair/test rounds and two fresh Anthropic Opus 5.5 high-reasoning reviews. Keep the architecture and acceptance criteria fixed. Close concrete blockers, not every architectural preference. The prior one-pass stop was assistant-imposed, not a user requirement.

## Confirmed findings and decisions

| Report item | Confirmation | Correction and planned proof |
|---|---|---|
| 1, must-fix | `replace` accepts a whole body, but only span reads exist | Full-page reads and a complete base/deletion diff in replacement review. Compiler test and G1 partial-replacement case. |
| 2, must-fix | Curator actor, credential placement and proposal discovery are unspecified | Dedicated non-delegating reviewer process, separate OS identity/secret, paged pending list, bounded backlog and own-proposal visibility. G3/G4 target curator injection and inheritance. |
| 3, must-fix | Numeric barriers can alias after restore | Project/epoch/sequence barriers, new restore epoch and non-reused creation-epoch/random IDs. Negative type tests and G3 same-sequence/different-history case. |
| 4, should-fix | No consuming tokenizer is identified in recall input | A 24,000-byte UTF-8 response cap, metadata included, independent of model tokenization. G2 measures emitted bytes. |
| 5, should-fix | Model-generated retry keys and per-child credentials are not justified | Trusted host/gateway journals keys before sending, resumes lost replies, allows shared worker principals and flags duplicate payloads. Do not substitute server-generated keys returned only after commit. |
| 6, should-fix | Strict freshness is the default despite asynchronous indexing | Best-available labeled coverage by default, strict opt-in, no absence inference from degraded retrieval. |
| 7, should-fix | Accepted captures lack a public/private visibility rule | Recall/index/export include only published eligible evidence. Pending/rejected text is owner/curator-only. |
| 8, should-fix | Corpus construction has no separate budget and answer model is unnamed | Add a corpus budget, explicit global stop precedence, a pinned baseline answer profile and host subset checks. |
| 9a, consider | Tail scan duplicates transactional lexical coverage | Adopt simplification: FTS5 lexical plus QMD vectors, no pending-tail scan or incomplete mode. No old recall score transfers to the new combination. |
| 9b, consider | Conflict terminality is ambiguous | Conflict is terminal for that proposal; rebase requires a new proposal and review. |
| 9c, consider | Tombstone semantics are ambiguous | A retired PageId is occupied, not absent. Create cannot reuse it. |
| 9d, consider | Citation hash scope is unspecified | SHA256 of the full stored UTF-8 body/text, not the selected span. |
| 9e, consider | Small slice thresholds can be misleading | At least 30 held-out positives per measured hard slice, with overlap recorded and uncertainty reported. |
| 9f, consider | Profile relaxation could disguise failed measurements | Post-hoc changes retain the original failure and require owner approval plus a fresh release gate. |
| 9g, consider | No owner for changing a blocked-host profile | The project owner can approve a scope change. Otherwise stop without treating a new CLI session as a native child. |
| 9h, consider | Upstream fixed-path swap is not a pinned-generation reader | Immutable generation directories, search-only access and an explicit no-mutation/provider-fit gate. Do not invent an unsupported QMD read-only option. |

These clarifications implement the user's request to fix the gaps. They preserve database authority, scoped MCP access and sequential hosts. No larger architecture replacement or new backend is proposed.

## Earlier repair evidence, historical

Baseline: existing research suite 14/14 passed. New compile-only contract tests failed against the old API. The red output is isolated under `.cache/architecture/opus-contract-red.log`.

Local results: strict TypeScript 5.9.3 compilation passes. Removing the seven expected-error annotations produces seven real diagnostics, so negative assertions are exercised. All 10 verifier unit tests and all 14 research tests pass. A new test first reproduced malformed review metadata causing a checker exception, then passed after the checker failed closed.

That snapshot's NEEDS-REVISION correctly blocked readiness despite the older READY report. The [prior Opus verification](arena/opus-5-5-fix-verification.md) completed with high reasoning, 9 source reads and a [source-bound receipt](arena/opus-5-5-fix-verification.json). It confirmed the original corrections and found the new lifecycle gap below. Its assistant-imposed stop is historical and does not restrict the current authorized repair.

## Consolidated closure dispositions

| Finding | Applied correction and proof boundary |
|---|---|
| M1, must-fix: blocked backlog can wedge admission | Complete state table; authorized metadata-only rejection; transactional slot release without deletion; default blocked housekeeping before long reviews; known-oversize preflight. Positive rejection/negative publication type tests pass. Real fill/reject/restart/race tests are specified in G1/G3, not claimed executed. |
| V1, must-fix: contradictory report can pass READY | Permanent red/green checker regressions. Require one exact leading verdict, agreement with metadata/optional receipt verdict, and current hashes for architecture, contract, delivery, checker and both test files. Conflicting, duplicate and example-only verdicts fail closed. |
| S1: worker versus curator OS identity | DELIVERY now names the worker account plus isolated service/curator identity. Authority files and curator credentials are not worker-readable. |
| S2: host journal has no type | Minimal `HostCallJournal.prepare` overloads accept key-free propose/decide intents and return the keyed request only after durable prepare. Compiler exercises both. Private adapter recovery/receipt storage remains a real-host gate. |
| S3: PageId after restore | Logical client names are distinct from server-generated epoch/UUID identities. Uniqueness means retained history; a lost name can be reused, but an exact lost revision/hash citation never aliases the new content. G3 tests both. |
| S4: curator self-proposal/approval | Curator client no longer exposes propose; the compiler rejects it. Server policy explicitly denies curator submission and self-approval, with forged-MCP tests in G3. |
| S5: lexical citation granularity | FTS indexes immutable line-span chunks carrying full-body hashes. QMD uses manifest-to-authority line mapping; both branches re-read exact authorized lines. G2 tests mapping and long lines. |
| Process wording | Remove the claim that the user imposed the earlier one-pass cap. Preserve it only as historical analysis context. |

All known corrections were applied together. The [fresh closure review](arena/closure-review.md) returned READY-FOR-IMPLEMENTATION with no remaining must-fix, and [its receipt](arena/closure-review.json) binds the six decision-critical files. The final readiness gate exits 0. Local checks include 17 checker tests, 14 research tests, 12 actual negative type diagnostics and compilation of the architecture example. These checks do not prove service behavior; G0-G8 remain unrun.

## Nonblocking closure-review follow-ups

| Review note | Disposition without reopening the frozen design |
|---|---|
| Normalize other Markdown verdict heading forms | Deferred robustness work. The accepted protocol uses one exact leading heading; indented/other-level verdict-looking lines are not counted today. Do not expand the reporting format without parser/regression changes. Current conforming closure report is unambiguous. |
| Show pagination in the usage example | The example illustrates one batch; the normative bounded scan/cursor policy already requires all pages before long reviews. Implement and test the full scan in P1; no larger example or second design review is needed. |
| Outages cause terminal rejections | Intentional bounded default, not lost data. Text and receipts survive; operation lookup exposes outcomes. The design already requires a new explicit proposal for corrected work. Distinguish infrastructure timeouts in the implementation's operator alerts; do not add automatic requeue now. |
| Name the journal call-ID reuse error | Defer transport/error mapping to the host adapter, consistently with the existing key-reuse error. Changed-payload reuse is already forbidden and cannot mint a replacement intent. No new public operation is needed. |

Used one repair round and one Opus call. None of these nonblocking notes changes the approval's source snapshot or warrants another architecture loop.

Verification: `python3 specs/wiki-system/verify.py` and the commands in [VERIFICATION.md](VERIFICATION.md).
