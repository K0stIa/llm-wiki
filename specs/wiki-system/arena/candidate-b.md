# Database-authoritative shared knowledge

## Usage (caller’s view)

Connect once to an authenticated project endpoint; independent sessions and actual child agents use the same service identity, not shared transcripts.

```ts
import { connectKnowledge } from "@project/knowledge";

// Coding: retrieve decisions, evidence, and related implementation details.
const k = await connectKnowledge(projectEndpoint);
const context = await k.recall("Why does refresh reject rotated tokens?");

// Learning: capture evidence and propose a reviewed-page replacement.
const receipt = await k.propose({
  key: retryKey, page: "auth/refresh", base: context.pageRevision,
  body: correctedExplanation, evidence: [sourceSnapshot]
});

// Independent reviewer agent: publish against the exact reviewed revision.
const decision = await reviewer.decide({
  key: reviewKey, proposal: receipt.proposal, action: "publish"
});
```

`propose` means durable proposal acceptance, **not publication**. `decide` requires reviewer authorization. Recall returns revision-scoped citations, coverage warnings, and index freshness.

## Shape

### Not-implemented API sketch

```ts
// Opaque, validated identifiers; SDK/MCP/SQL types remain internal.
type Revision = Opaque<"Revision">;
type ProposalId = Opaque<"ProposalId">;
type Key = Opaque<"IdempotencyKey">;

interface Knowledge {
  recall(query: string): Promise<{
    passages: Passage[]; pageRevision?: Revision;
    committedThrough: number; indexedThrough: number;
    warnings: string[];
  }>;
  propose(input: {
    key: Key; page: string; base?: Revision;
    body: string; evidence: EvidenceSnapshot[];
  }): Promise<{ proposal: ProposalId; state: "pending" }>;
  decide(input: {
    key: Key; proposal: ProposalId;
    action: "publish" | "reject";
  }): Promise<
    | { state: "published"; revision: Revision }
    | { state: "rejected" | "conflict" }
  >;
}
// All implementations: throw new Error("not implemented").
```

Passages cite immutable evidence/page revision IDs, content hashes and source locators; evidence snapshots contain captured bytes, not merely mutable URLs. Boundary validation creates opaque IDs and checks authorization (`boundary-discipline`).

### Authority and module map

| Module | Owns |
|---|---|
| `knowledge` | SQLite authority: projects, immutable evidence, reviewed revisions, current-page pointers, independent proposals, decisions, idempotency receipts, transactional outbox |
| `retrieval` | Rebuildable FTS5/vector projections, chunking, fusion, expansion, citation validation and coverage reporting |
| `hosts` | MCP transport, authenticated project binding, host-specific tool exposure and actual-child setup |
| `exports` | Disposable Markdown views with revision manifests; never authoritative |

Use SQLite transactions, FTS5, sqlite-vec (MIT), and an official MCP SDK; preserve notices and pin versions. The new gap is curation, isolation and recovery policy—not another embedding engine. Existing Pi LLM Wiki document/citation formats and QMD recovery patterns are adaptation candidates, not parallel authorities.

**Concurrency:** proposals are per-actor immutable records (`separate-before-serializing-shared-state`). Publication compares the proposal’s base with the current revision inside one transaction. Competing same-page proposals survive; only one matching-base publication succeeds. Conflicts require a new, reviewed rebase proposal, never last-writer-wins merging.

**Retries and crashes:** project/principal/key uniqueness plus payload hashes distinguish replay from key misuse. Publication atomically records the revision, pointer, decision, receipt and outbox event. A crash after commit but before reply returns the stored receipt on retry. Index workers consume idempotently. Markdown export happens afterward; no database/filesystem atomicity claim.

**Retrieval:** lexical, semantic and linked-page candidates are fused and expanded under a token budget. Pending-vector revisions remain searchable through transactional FTS and bounded recent-revision fallback. Revalidate candidates against authorized current state; report incomplete coverage rather than hiding stale-index limitations. Historical citations resolve exact revisions and identify supersession. Evidence and synthesized knowledge remain visibly distinct.

**Isolation:** authenticated capabilities bind project and role server-side, never cwd, tags or model text. Every lookup, citation and index partition includes project identity. Retrieved instructions remain untrusted data. No cross-project search by default.

Three public operations hide publication, recovery and ranking complexity (`interface-depth`); callers retain only query, proposal and review intent.

## Problem

GROUNDING documents lost concurrent writes, separate indexing lifecycles, existing MCP support and unverified host integration. Durable shared knowledge therefore needs transactional publication and explicit visibility states, not transcript persistence. This artifact is a contract and plan; no prototype, runtime test or deployment occurred.

## Synthesis decision

This candidate selects database authority. No unseen candidate comparison is claimed. Markdown is a view; indexes are replaceable.

## Tradeoffs accepted

- We accept single-machine SQLite write serialization for atomic publication and simple recovery.
- We accept a small application schema for explicit review and isolation.
- We accept declared semantic degradation when approved embeddings are unavailable, not an unmeasured high-recall claim.

## Alternatives considered

- **MCP Memory Service:** Apache-2.0; its reviewed README and `storage/sqlite_vec.py` show shared persistence, hybrid retrieval and storage mixins. They do not establish a public atomic curation/CAS API. Forking publication and isolation internals would erase much of the reuse advantage; retain it as an evaluated alternative, not authoritative through assumed transactions.
- **Markdown authority plus QMD:** hides retrieval well, but exposes cross-file publication/recovery coordination. Database authority keeps that complexity inside one boundary.

## Open questions and risks

- Will measured corpus size or concurrent writers exceed a single-machine deployment?
- Which embedding weights, hardware budget and trust boundary are approved?
- What retention and deletion policy should immutable evidence follow?

Reversible defaults: one authenticated local service, separate project namespaces, no SaaS, cluster, implicit downloads or mandatory QMD.

## Next implementation step

Build the transactional publication/replay vertical slice with disposable retrieval and a Pi parent/child client.

## Delivery and evidence gates

1. **Ground → sketch → agreement:** completed for this candidate; agreement is automated contract review, not a human checkpoint.
2. **Prototype:** proposed limit: three implementation/test iterations, then one redesign and two repair iterations; otherwise stop with reproducible blockers.
3. **Core gate:** crash injection, duplicate requests, competing proposals, stale indexes, project-denial tests and backup/restore must show zero lost accepted writes or unauthorized results.
4. **Retrieval gate:** representative held-out coding questions, independently labeled evidence; proposed Recall@20 ≥90%, exact citation resolution 100%; latency budgets follow hardware measurement. Tiny fixtures are regression tests only.
5. **Host gates, strictly sequential:** Pi → Codex CLI → Claude Code → OpenCode. Each requires fresh-session recall and actual native-child read/propose/reviewer behavior. Validate installed schemas and allowlists; unsupported child behavior blocks that host.
6. **Final gate:** an independent agent reruns adversarial scenarios and verifies receipts, database revisions and host transcripts—not implementer summaries.

Publish only sanitized clean-history artifacts; preserve operational access and unrelated work.

## Red-flags self-check

No generic pass-through pipeline; ownership is explicit. No wire-type leakage, dual authority, automatic trust promotion, unsupported transaction claim, or source-review-as-runtime-test claim.
