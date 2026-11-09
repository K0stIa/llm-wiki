# Candidate A: document-authoritative project knowledge

## Usage (caller's view)

Clients connect to one authenticated project service; cwd and session identity never select the project. Examples are contractual, not implemented:

```ts
import { connectKnowledge } from "@project/knowledge";

// Independent session: recover decisions with revision-bound citations.
const wiki = await connectKnowledge(projectCapability);
const answer = await wiki.recall({ query: "Why retry payment callbacks?" });

// Actual child: host launches it with its own tools and project capability.
const childAnswer = await childWiki.recall({ query: taskQuestion });

// Curate a correction; retry the identical request after a lost reply.
const result = await wiki.propose({
  request: stableRequestId,
  page: retryPolicyPage,
  base: citedPageRevision,
  markdown: correction,
  evidence: answer.hits.map(h => h.citation),
});
```

`propose` returns pending, committed, conflicted or rejected—not an indexing promise. Children receive scoped service access, not merely a parent's summary.

## Shape

### Concise TypeScript contract

```ts
type Opaque<K extends string> = string & { readonly kind: K };
type Page = Opaque<"Page">;
type Revision = Opaque<"Revision">;
type RequestId = Opaque<"Request">;
type Citation = {
  page: Page; revision: Revision; fragment: string;
};
type Recall = {
  hits: { text: string; citation: Citation }[];
  accepted: Revision; indexed: Revision | null;
  coverage: "complete" | "degraded";
};
type Proposal = {
  request: RequestId; page: Page; base: Revision | null;
  markdown: string; evidence: Citation[];
};
type Outcome =
  | { state: "pending"; request: RequestId }
  | { state: "committed"; revision: Revision }
  | { state: "conflicted"; current: Revision }
  | { state: "rejected"; reason: string };

interface Knowledge {
  recall(input: { query: string }): Promise<Recall>;
  propose(input: Proposal): Promise<Outcome>;
  status(request: RequestId): Promise<Outcome>;
}
async function connectKnowledge(
  capability: Opaque<"ProjectCapability">
): Promise<Knowledge> {
  throw new Error("not implemented");
}
```

Wire schemas, SQLite records and host SDK types remain internal. Validate capabilities, paths, evidence references and proposal sizes at ingress, per boundary-discipline.

### Module map and ownership

- **Authority:** immutable Markdown/evidence objects, revision manifests and project HEAD; owns publication, revision reads and recovery.
- **Proposals:** SQLite operational inbox, idempotency keys, payload digests and policy decisions; never an authoritative page-content store. Draft payloads reference immutable draft documents.
- **Retrieval:** generated lexical/vector indexes and coverage watermark; owns ranking, authorization revalidation and current-document fallback.
- **Hosts:** Pi native/MCP and subsequent MCP adapters; own configuration validation, capability propagation and actual child-tool availability.

MCP handlers invoke these owners directly; no generic load/transform/save pipeline.

### Durable publication contract

Assume initially one trusted local machine, durable POSIX storage and one publisher holding an OS-exclusive project lock. Multiple client processes submit independently; they never publish directly. Reject unsupported network-filesystem semantics.

Each proposal has a private draft. A unique `(project, request)` binds its digest; changed payloads under the same key fail. The publisher compares the proposal's base with the current **page** revision. Same-page competitors conflict; unrelated pages may proceed. Automatic three-way merging is deferred; a revised proposal names the new base.

Publication writes and fsyncs immutable page/evidence objects, then an immutable manifest containing the parent revision, page map and request outcome. After syncing directories, atomically replace HEAD and sync its directory. That durable HEAD replacement is acceptance's linearization point. Only then report committed.

SQLite and Markdown are **not** one transaction. Startup recovery under the publisher lock walks HEAD's accepted manifest chain, reconstructs committed request outcomes, reconciles pending rows and schedules indexing. A crash after commit but before reply returns the same revision on retry. A crash before publication leaves harmless unreferenced objects; an interrupted durability boundary is resolved from recovered HEAD, never guessed from SQLite.

Revision citations resolve immutable content; current retrieval filters superseded hits. Retention must preserve cited revisions.

### Retrieval path

Reuse Pi LLM Wiki's document parsing, source separation and MCP transport. Adapt its QMD mirror validation, locking and journaled index replacement before inventing equivalents. Keep lexical retrieval functional without models; QMD is replaceable.

Search combines lexical, semantic and backlink/evidence expansion. Embeddings and reranking require explicitly approved models and licenses—no implicit downloads. Each request pins accepted HEAD, validates every candidate against that snapshot and project authorization, and scans changed documents since the index watermark. If that fallback exceeds its configured budget, return degraded coverage explicitly. Generated indexes are rebuildable, never authoritative.

## Problem

GROUNDING.md describes experiments, not deployment: multi-process captures and same-slug edits lost writes; document writes do not atomically refresh metadata or vectors. Durable knowledge must survive sessions while remaining accessible to real children. Retrieved evidence is untrusted data, not executable project policy.

## Synthesis decision

This is Direction A only; no unseen candidate comparison is claimed. Choose document authority for auditable revision identity; reuse existing MIT Pi LLM Wiki/QMD components. Verify pinned licenses and maintenance before adoption.

## Tradeoffs accepted

- Accept serialized publication for simple, recoverable ownership.
- Accept immutable-object storage growth for stable citations.
- Accept observable degraded recall rather than pretending stale vectors are complete.

## Alternatives considered

- **Database-authoritative wiki:** hides stronger transactional editing behind a similarly small API, but violates Direction A's document authority.
- **Direct multi-writer Markdown plus watchers:** exposes locking, recovery and freshness coordination to callers; observed losses reject it.

## Open questions and risks

- What corpus, hardware and latency budget should replace provisional benchmark thresholds?
- Does deployment require hostile-user isolation or remote access? Initial capabilities enforce project boundaries on a trusted host, not a public SaaS perimeter.
- Which embedding weights and evidence-retention policy are acceptable?

## Next implementation step

Build the authority/recovery prototype against this contract in an isolated workspace with clean history.

## Delivery and evidence gates

No implementation or runtime test occurred here. No human checkpoint is introduced.

1. **Prototype:** maximum two build/test iterations; fault-inject publication boundaries, duplicate retries, same-page races, cross-project access and stale indexes.
2. **Pi gate:** real parent, actual child and fresh independent session must retrieve committed knowledge.
3. **Sequential hosts:** Codex CLI → Claude Code → OpenCode; validate installed schemas and repeat those tests before advancing.
4. **Acceptance:** proposed thresholds: zero lost acknowledged writes, zero cross-project disclosures, ≥95% evidence recall on a held-out representative corpus. Tiny fixtures and source review do not qualify. Record latency/resource measurements before setting SLOs.
5. **Independent final agent:** separately inspect artifacts and rerun acceptance against the release candidate. Permit one correction/reverification cycle; otherwise stop with failed gates and residual risks.

Preserve operational access, unrelated work and global configuration. Publish only clean-history application/vault artifacts, never existing repository history.

## Red-flags self-check

Three public operations hide persistence and retrieval complexity; no SDK leakage, temporal modules or pass-through pipeline. Repeated architectural deviations trigger redesign, not expanding escape hatches.
