# Cross-judge review

**Recommend Candidate B as the stronger base**, with two grafts from A. B’s database authority is permitted by GROUNDING.md and makes publication, receipts and indexing work atomic without a filesystem/database reconciliation protocol.

Both candidates and the grounding were read end to end. The rubric’s referenced `architect/references/design-red-flags.md` was unavailable at the repository-relative path; that external screening remains incomplete. Neither candidate’s self-check substitutes for it.

## Scores

Scores assess design contracts, not implemented behavior.

| Criterion | A | B | Assessment |
|---|---:|---:|---|
| Durable authority and concurrency | 3 | 4 | A specifies durable HEAD publication and recovery, but pending-proposal durability and page-versus-project revision types remain ambiguous. B atomically couples revision, pointer, decision, receipt and outbox. |
| Recall with evidence | 3 | 3 | Both provide revision citations, hybrid search and observable degradation. A pins reads to HEAD; B explicitly budgets context. Neither defines evidence insufficiency or abstention adequately. |
| Reuse and interface depth | 4 | 3 | A directly incorporates grounded Pi/QMD indexing and transport capabilities. B has a coherent small interface, but needs a firmer justification for selecting new retrieval components over existing adapters. |
| Actual-agent compatibility | 4 | 4 | Both require shared authenticated identity, actual children, independent sessions and sequential host gates rather than treating MCP registration as proof. |
| Bounded delivery and verification | 3 | 3 | Both bound implementation iterations and require independent verification. Neither explicitly freezes the holdout or defines release rollback; B’s final verification retry/stop policy is less clear. |
| Security and operations | 2 | 3 | A lacks an explicit read/propose/publish role model and backup gate. B adds reviewer authorization and backup/restore testing, but neither fully specifies capture-access restrictions, deletion or operational recovery. |
| **Total / 24** | **19** | **20** | **B narrowly leads.** |

## Authority and transaction findings

**A is genuinely document-authoritative**, not SQLite authority disguised behind Markdown. Immutable objects and manifests become accepted through durable HEAD replacement; SQLite is a recoverable operational projection. Same-page CAS and serialized publication address the observed lost-update failures. Its cross-store coordination is explicit rather than falsely described as atomic.

However, A must specify when `pending` becomes durable, how draft creation and inbox insertion recover together, and how rejected/conflicted receipts persist. Committed outcomes can be reconstructed from manifests; the same guarantee is not established for every other outcome. Its single `Revision` type also conflates page revisions with project HEAD/index watermarks. The initial deployment additionally depends on enforced single-publisher ownership and verified storage semantics.

**B centralizes the relevant publication invariant in one transaction.** Markdown exports and indexes cannot overwrite authority. Separate immutable proposals preserve competing work; reviewed rebases prevent quiet last-writer-wins publication. This is a substantive simplification, not an API naming preference.

B still needs precise semantics for omitted `base`, repeated decisions with different keys, and immutable proposal-to-review binding. Its claimed “transactional FTS” must be made part of the publication contract or replaced by a clearly bounded catch-up guarantee. Candidate validation against “current state” should also identify one consistent read snapshot.

**No demonstrated disqualifier applies.** Neither claims completed runtime tests, and neither specifies an acknowledged-write-loss path. Missing crash details are risks, not proof of such a path. B’s assertion that automated agreement is “completed” has no accompanying evidence and receives no credit.

A’s rejection of database authority because it violates “Direction A” is not a user constraint: grounding explicitly permits databases.

## Exactly two useful grafts

1. **Graft A’s snapshot-bound retrieval into B.** Pin each recall to a committed revision/watermark, validate citations and authorization against that snapshot, and bound changed-document fallback with explicit incomplete coverage.
2. **Graft A’s concrete reuse obligations into B.** Evaluate the existing Pi parser, source separation, MCP transport and QMD mirror/index-recovery modules before implementing replacements. Keep B’s database as the sole authority; imported indexing mechanisms remain projections.

## Most important rejected idea

**Reject preserving document authority merely because Markdown is desirable or a candidate direction demands it.** B can export auditable Markdown and retain immutable cited revisions without accepting A’s additional HEAD/inbox reconciliation burden. This does not make A inherently unsafe; it makes that complexity unjustified by the supplied requirements.

## Three highest-risk questions

1. What exact transaction, durability settings and replay state machine govern proposals, reviews, omitted bases, repeated decisions and crash recovery?
2. How will snapshot-consistent, authorized recall handle stale projections, insufficient evidence and bounded fallback without hiding omissions?
3. What enforced role, evidence-ingestion and backup/restore boundaries prevent unauthorized publication, arbitrary filesystem/network access and irreversible loss?
