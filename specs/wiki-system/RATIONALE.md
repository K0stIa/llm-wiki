# Architecture rationale and arena decision

## Problem

Independent sessions and real child agents need durable, high-recall knowledge with evidence. The existing experiments exposed silent concurrent write loss and lexical misses. They did not establish production behavior. Markdown authority, databases and QMD were choices, not user constraints. [Grounding](GROUNDING.md) also found existing MCP and QMD lifecycle code that a new system must reuse where safe.

## Usage, caller's view

A coding agent connects to a project-bound service, retrieves exact evidence and submits an immutable proposal. A separately authorized curator reviews that proposal and publishes against its base revision. Fresh sessions and children use the same tools and service identity. [The usage examples](ARCHITECTURE.md#usage-written-before-the-types) were written before [the type contract](contract.d.ts).

## Shape

Choose database authority with derived Markdown/OKF exports and QMD search indexes. SQLite commits evidence, proposals, revision checks, receipts, FTS and indexing work atomically. MCP clients never coordinate those steps themselves, per interface-depth and boundary-discipline.

A small domain API supports recall, complete page reads, exact citations, proposals and private operation receipts. Curators add paged work discovery, full-base/diff inspection, review-attested publication and metadata-only rejection. It hides storage, recovery and ranking without exposing SQL or SDK types. Separate page/project/index identities and discriminated outcomes prevent ambiguous revision and freshness states, per type-system-discipline. Keep independent proposals separate until one reviewed CAS publication, per separate-before-serializing-shared-state.

## Synthesis decision

The two candidates explored genuinely different authorities. Both ran on configured `gpt-6.1-sol`. Their first high-thinking attempts reached the 240-second deadline. Each received one medium-thinking retry, producing complete artifacts in 66 and 82 seconds. No partial timeout artifact became a candidate.

The independent `gpt-6-astra` judge read both completed artifacts. It narrowly preferred B. The supervisor also read both end to end and agrees.

| Criterion, 0-4 | A, document authority | B, database authority |
|---|---:|---:|
| Durable authority/concurrency | 3 | 4 |
| Recall/evidence | 3 | 3 |
| Reuse/interface depth | 4 | 3 |
| Actual-agent compatibility | 4 | 4 |
| Bounded delivery/verification | 3 | 3 |
| Security/operations | 2 | 3 |
| Total | 19 | 20 |

These are design judgments, not runtime scores. Original artifacts: [A](arena/candidate-a.md), [B](arena/candidate-b.md), [cross-judge](arena/cross-judge.md).

B wins because it makes the publication invariant one transaction. A specifies a plausible durable HEAD/manifest protocol, but also needs reconciliation between accepted filesystem state and operational SQLite state. No supplied requirement justifies that extra protocol.

Graft two ideas from A:

1. Pin recall to one accepted snapshot and report bounded catch-up coverage explicitly.
2. Reuse concrete Pi Wiki parser/MCP/QMD mirror/recovery components before writing replacements.

Reject A's filesystem authority protocol, not its useful format or citation conventions. Reject B's extra sqlite-vec retrieval stack for the first build; QMD already has stronger local measurements. Reject B's unsupported statement that automated agreement was completed. This synthesis, not that assertion, is the decision record.

Both candidates omitted enough abstention, retention, HTTP and rollback detail to require revision. The synthesized design adds those contracts and a frozen holdout. It gives idempotency, terminal decisions, transactional FTS and stale reads precise meanings rather than inheriting ambiguous sketches.

### Red-flags screen before synthesis

| Screen | A | B and synthesized correction |
|---|---|---|
| Shallow modules | Authority is deep, but callers risk learning HEAD recovery details | Keep coordination inside authority; exact-read/receipt methods hide necessary behavior |
| Information leakage | One revision type conflates page and project identities | Distinct branded identities; no public SQLite, QMD or MCP types |
| Temporal decomposition | Manifest publication and inbox recovery cross boundaries | One transactional owner; indexing remains a derived capability |
| Pass-throughs | No material forwarding pipeline | Keep host adapters only for authorization, protocol and real host differences |

The cross-judge did not read the correct absolute red-flags reference. The supervisor did and applied this screen to both candidates before selecting the base. That limitation remains visible in the saved judge artifact.

### Independent review after synthesis

A fresh reviewer found snapshot races, ambiguous retry lookup and related type/policy gaps. One correction cycle pins index generations before SQLite snapshots, captures FTS inside the read transaction, separates proposal state from private receipts and makes key identity consistent. It also tightens degraded-search and expanded-link rules. The [original findings](arena/design-review.md) and [review rerun](arena/final-review.md) are preserved. The rerun says READY-FOR-IMPLEMENTATION, not production ready. Runtime G0-G8 remain unrun.

### Opus confirmation and correction

The additional Anthropic Opus 5.5 high-reasoning review found concrete missing contracts, not a reason to replace database authority. [The repair ledger](OPUS_FIXES.md) confirms every finding and records its disposition. Full-page review prevents hidden replacement deletions. A dedicated non-delegating curator, separate credential identity and durable pending discovery define who publishes. Project/epoch/sequence barriers and non-reused IDs prevent restore aliasing.

The correction also moves retry identity into trusted durable host journals, defines private evidence eligibility and replaces the unknown-model token estimate with a byte cap. FTS5 plus QMD vectors removes redundant lexical/tail branches. Best-available labeled context is the default; strict semantic freshness is opt-in. This configuration requires its own benchmark and inherits no earlier recall score. The subsequent review found blocked-queue recovery missing. The closure patch keeps the same authority, adds terminal metadata rejection and known-oversize admission checks, and preserves acknowledged evidence. Rejection is not a claim that a model reviewed the body. The checker also rejects contradictory verdicts and binds readiness to the checker/tests as well as the three design files. These local fixes do not justify replacing the architecture. The [fresh closure review](arena/closure-review.md) verified these corrections and returned READY-FOR-IMPLEMENTATION. Its four nonblocking notes are recorded rather than used to restart architecture exploration. Runtime readiness still requires G0-G8.

## Tradeoffs accepted

- Accept SQLite write serialization for atomic publication and simpler replay.
- Accept a small new curation schema instead of assuming a memory API supplies CAS/review transactions.
- Accept immutable revision storage growth for stable citations. Retention and legal deletion remain explicit deployment decisions.
- Accept observable unavailable/degraded recall rather than hiding stale semantic coverage.
- Accept generated Markdown rather than direct file editing as the publication mechanism.

## Alternatives considered

- MCP Memory Service can hide persistence and retrieval behind one API. Source review does not prove transactional curation or project authorization. P0 gives it one bounded fit test before custom coordination.
- A document-authoritative wiki directly reuses more file-writing code. Its atomic-publication and recovery protocol is larger for the required guarantees.
- Direct parallel Pi Wiki capture/retro writes are simpler only by dropping conflict and durability guarantees. The observed data loss rejects them.

## Open questions and risks

What real corpus, resource limits, retention policy and deployment trust boundary replace the prototype defaults? Which model weights are legally approved? Does the actual deployed child mechanism preserve the required tools in each host? P0 and host gates resolve these questions; source inspection cannot.

## Next implementation step

Run P0's upstream-fit and deployment-profile gate, then implement the isolated propose/review/commit/restart/read slice. There is no additional human design checkpoint.

Verification: `python3 specs/wiki-system/verify.py`. Runtime implementation and rollout remain unstarted.
