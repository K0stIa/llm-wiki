# Independent design-review rerun

## Verdict: READY-FOR-IMPLEMENTATION

The six original findings are resolved coherently at the design level. No new blocker was identified. This verdict covers the requested architecture, domain contract and bounded plan—not a deployed or production-verified system.

| Original finding | Resolution |
|---|---|
| Snapshot and index consistency | Recall pins and retains a generation **before** acquiring the SQLite snapshot. It captures `R`, FTS candidates, tail candidates and mappings within that transaction; rejects an ineligible generation; and does not switch generations mid-query. G2 tests intervening publication, promotion and retention. |
| Replay-key ambiguity | Keys are unique across operation kinds for each project/principal; kind is included in the request digest. Different-kind reuse fails, so `operation(key)` is unambiguous. G1 covers interrupted replies and cross-principal receipt isolation. |
| Semantic-tail overclaim | The design explicitly limits semantic search to indexed revisions and pending revisions to lexical search. It warns that paraphrases may be missed even within budget and prohibits absence inference from degraded results. G2 includes that miss. |
| Expanded-link authorization | Every expanded target, including evidence, is reauthorized for the project and snapshot; page targets must satisfy head and active-state checks. Historical material is labeled. G3 tests cross-project and retired/superseded links. |
| Proposal state versus private receipts | `ProposalState` is key-free and separate from principal-scoped `OperationState`. Curators can inspect proposals without receiving proposers’ retry keys; G1 checks this boundary. |
| Default versus degraded recall | The example explicitly opts into `allow-degraded`; the contract and architecture default to strict `require-hybrid-current` and specify `not-ready` otherwise. G2 exercises the weaker modes and failure path. |

The module ownership and domain-facing contract also pass the requested red-flag screen at this design stage: authority, retrieval and transport hide distinct responsibilities without exposing database or SDK types as the public model.

## Remaining blockers

None identified for implementation. The plan preserves the requested Pi → Codex CLI → Claude Code → OpenCode rollout order and makes unpassed safety-critical gates release blockers.

## Checks not performed

I read the original report, current architecture, delivery plan, contract and specified red-flags reference end to end. I ran no commands and performed no compilation, implementation, concurrency, retrieval, security, crash or actual-host tests. Source/model licensing, production application, host behavior and G0–G8 remain future work; this review does not certify them.
