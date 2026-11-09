# Shared coding-agent knowledge

Status: chosen design, not implemented. This document defines ownership and failure behavior. [The contract](contract.d.ts) defines the public types. [Delivery gates](DELIVERY.md) define proof of completion.

## Usage, written before the types

The service binds each client to an authenticated project and role. Sessions and worktrees use the same service identity. These examples describe the intended API.

```ts
// A fresh session gets best-available evidence with explicit coverage labels.
const knowledge = await connectKnowledge(projectConnection);
const context = await knowledge.recall({ query: "Why do rotated tokens fail?" });
// Inspect coverage. Strict semantic freshness is opt-in, never silently downgraded.

// Trusted host adapter code. Children can share the worker principal.
const base = await childKnowledge.page({ page: citedPage, revision: citedPageRevision });
const intent = await hostJournal.prepare({
  call: stableHostCallId, kind: "propose",
  request: {
    change: { kind: "replace", page: base.page, base: base.revision,
      title: base.title, markdown: correctedCompleteBody },
    sources: [capturedSource],
  },
});
const receipt = await childKnowledge.propose(intent.request);
// The journal persisted the key AND request before sending. Resume that intent
// after a lost reply, even if receipt was never received.

// The isolated curator discovers work without an out-of-band ID handoff.
const batch = await curator.pendingProposals({ limit: 20 });
for (const item of batch.items) {
  if (item.state.kind !== "blocked") continue;
  const rejection = await curatorJournal.prepare({
    call: stableRejectionCallIdFor(item.proposal), kind: "decide",
    request: { proposal: item.proposal,
      decision: { kind: "reject", reason: item.state.reason } },
  });
  await curator.decide(rejection.request); // Metadata only, no review attestation.
}
// The supervisor completes the bounded metadata scan before long reviews.
const nextPending = batch.items.find(item => item.state.kind === "pending");
if (nextPending) {
  const proposal = await curator.proposal({ id: nextPending.proposal });
  // Inspect the complete base, proposed body, deleted lines and cited evidence.
  const reviewIntent = await curatorJournal.prepare({
    call: stableReviewCallId, kind: "decide",
    request: { proposal: proposal.id,
      decision: { kind: "publish", reviewedDigest: proposal.reviewDigest } },
  });
  await curator.decide(reviewIntent.request);
}
```

These calls do not require agents to open SQLite, manipulate index files or coordinate publication steps. A normal agent cannot obtain curator authority by changing an input field.

## Chosen shape

```text
Pi -> Codex CLI -> Claude Code -> OpenCode, released in that order
             authenticated MCP read/propose clients
                              |
                 one project knowledge service
                 /             |              \
     knowledge authority    retrieval      host boundary
     SQLite + FTS5          QMD SDK        official MCP SDK
     revisions/proposals    generated      client configuration
     evidence/receipts      per-project    role/project binding
     review + outbox        indexes        actual child checks
                 \
                  generated Markdown/OKF export
```

One service on a single machine is the first deployment. SQLite lives on a local filesystem. Multiple clients submit proposals. One service-owned publisher decides accepted revisions. On the initial Linux deployment, the service launcher holds an OS-owned `flock` for the canonical authority path for its entire lifetime. A second instance fails startup; the kernel releases the lock on exit. Do not invent an expiring publisher lease. No shared SQLite over NFS, active-active replicas or public SaaS perimeter is implied.

### Ownership and module map

| Module | Owns and hides | Must not own |
|---|---|---|
| `knowledge.ts` plus its SQL migration | Immutable source/page revisions, proposals, page CAS, publication, receipts, review history, transactional FTS and outbox | Embedding SDK types, host sessions |
| `retrieval.ts` | Chunk/index manifests, lexical/vector fusion, revision validation, linked-evidence expansion and context limits | Accepted page contents or publication decisions |
| `mcp.ts` | Input schemas, authenticated project/role binding, tool authorization, errors and output limits | A second curation engine |
| `hosts/` | Small version-checked host setup and real-child fixtures | Alternate storage or recall logic per host |

Keep an authoritative operation readable within the boundary module and its SQL. Add files for independent knowledge, not for sequential load/validate/save stages. Markdown export belongs to the authority's read/export implementation, not a new framework.

## Database authority

Use real SQLite transactions. Enable foreign keys, WAL and `synchronous=FULL`; use a bounded busy timeout and explicit transaction retry policy. Bind values as parameters. Document filesystem and power-loss assumptions. A process-kill test alone does not prove protection from faulty hardware.

The application schema contains these records:

- `projects`, a restore epoch and a monotonic commit sequence within that epoch.
- `evidence_revisions`, containing captured UTF-8 text, its hash and provenance. Mutable URLs are locators, not evidence identities.
- `page_revisions`, containing immutable title/body, links, evidence citations, predecessor and review identity.
- `page_heads`, mapping a project/page to its current revision and active/retired state.
- `proposals`, containing immutable proposed changes, actor identity, base revision, source references and payload digest.
- `decisions`, immutable review outcomes bound to an exact proposal digest.
- `operations`, binding project, authenticated principal and idempotency key to the request digest and durable result.
- Transactional FTS5 entries and a durable index/export outbox.

Use compound foreign keys with project identity. Enforce one successful publication per proposal. Separate `PageRevision` from `ProjectRevision` and `IndexGeneration`. A `ProjectRevision` contains project, epoch and sequence; compare sequences only after matching project and epoch. The public contract never exposes table names.

### Proposal and publication state machine

1. Validate size, authorization and citations before accepting a proposal. Preflight the complete review bundle against the frozen curator profile described below. In one transaction, recheck the unresolved cap and insert captured text, the immutable proposal and its operation receipt. Commit before returning `pending`. Known oversize requests return capacity before captures or proposals are accepted.
2. Bind idempotency to project, principal and key across all operation kinds. Include the operation kind in the request digest. An identical retry returns its original durable receipt. Any different payload or operation kind under that key fails with `key-reuse`. `operation(key)` is therefore unambiguous. It reports proposal progress or the recorded decision without exposing another principal's retry key.
3. A create requires a logical PageId absent from the retained authority history. A retired PageId remains occupied; create and replace cannot reactivate it in this release. A replacement or retirement requires an explicit active base page revision. Omitted bases are invalid, not unconditional overwrites.
4. `page` returns the complete immutable body, title, hash and state at the requested revision. Never silently truncate it. Replacement review includes that full base, the complete proposed body and a deletion-visible diff. A distinct `ReviewDigest` binds this bundle, its source citations and the current authority epoch. The curator reads it before publication. A publish request attests that review digest, not only the proposal payload digest. Post-admission review failures become `blocked`, not partly reviewed approvals. Known oversize bundles fail admission instead. No proposal inspection exposes another principal's operation key.
5. Inside `BEGIN IMMEDIATE`, compare the current page head with the proposal base. On success, insert the revision, advance the head and project sequence, record the decision and receipt, update FTS and enqueue index/export work. Commit them together.
6. A competing same-page edit returns `conflict` with the current revision. Conflict is terminal for that proposal. Keep both proposals. A rebase is a new proposal with a new review, not a silent last-writer-wins merge.
7. Authorized rejection is valid for pending or blocked proposals and needs only the proposal ID, reason and journaled operation key. It is not a claim of full review. In one transaction, record its immutable decision/receipt and release its unresolved slot; keep the proposal and evidence. Do not change page heads, FTS, outbox or the publication sequence. A terminal proposal cannot be changed by a later request under another key. An identical terminal decision can return the existing result; contradictory decisions fail.

| Current state | Request/event | Result |
|---|---|---|
| pending | Authorized publish, full current-epoch review, head CAS succeeds | decided/committed |
| pending | Same publish, head CAS loses | decided/conflict |
| pending | Service-owned review supervisor records context/evidence/policy failure or deadline | blocked with reason |
| pending or blocked | Authorized metadata-only reject | decided/rejected; unresolved capacity released |
| blocked | Publish | invalid-state, no publication |
| decided | Identical decision replay within the epoch/retry policy | Original durable result, no second transition |
| decided | Contradictory decision or later blocked event | terminal-decision or no-op supervisor event, never mutation |

All state transitions serialize in the authority transaction. Unlisted model-requested transitions return invalid-state; repeated supervisor notifications after leaving pending are no-ops. A late review completion cannot publish after a blocked/rejected transition. The service-owned curator supervisor records blocked outcomes; this is not an arbitrary worker tool. Returning blocked work to pending is not supported: corrected work requires a new explicit proposal. A retry is not a new proposal.

At G0 freeze the curator model/context size, review input budget, fixed policy/tool wrappers, maximum output reserve and counting method. Use a pinned tokenizer or a validated conservative bound; inability to establish the bound blocks G0. Admission builds the complete base, proposed body, deletion diff and resolved cited evidence in memory against immutable revisions, and proves the complete request plus reserve fits. A later profile change or infrastructure failure can still block accepted work; use metadata rejection, never truncation. This preflight does not promise review quality or completion time.

Crash before commit means no accepted operation. Crash after commit but before reply means a retry returns the committed receipt. An accepted operation never depends on an in-memory queue. SQLite busy, disk-full and validation errors must not return a success receipt.

Publication does not mean embeddings are visible. The receipt names the committed project revision; freshness reports index visibility separately. Read-your-write requests name `atLeast`. Reject a different project or epoch before any sequence comparison. A same-epoch future sequence returns unavailable, never a fabricated visibility claim.

### Restore identity and exact reads

A normal restart keeps the epoch. Every backup restore or authority fork creates a fresh unpredictable epoch before serving requests, even when restoring in place. In maintenance, atomically set the new epoch, invalidate old index/outbox targets and review attestations, and enqueue a full rebuild for the restored heads under the new epoch. An old `atLeast` returns `stale-epoch` forever; reaching the same numeric sequence later cannot satisfy it. Pending proposals retain their contents but require a fresh current-epoch review. Invalidate pending transport mutations from the old epoch. Do not automatically replay an old mutation under a new key.

New proposal, source, page-revision and operation IDs use their creation epoch plus a random UUID, never counters or row counts. Retained IDs and citations keep their identity after restore. Missing old server-generated IDs return not-found and cannot be reallocated to new content. Logical client-chosen PageIds are different: a lost post-backup create can leave that name available after restore. Exact old citations still require the non-reused revision and hash, and never resolve to the new page. Historical operation lookup can return an exactly retained receipt; it cannot prove lost post-backup work survived. New mutations always use the current epoch.

`Citation.hash` is SHA256 of the entire stored UTF-8 markdown/text body without normalization, not of the selected span. Spans are inclusive, 1-based LF-delimited lines. Exact reads validate identity, hash, span and authorization; they never redirect to another revision.

### Retry ownership and private proposals

The trusted host/gateway adapter, not the model, generates a random epoch-scoped operation key. It durably records the stable host call identity, key, request bytes/digest, project and principal before sending. Model-facing MCP schemas omit `key`. The low-level TypeScript client accepts it only from that adapter. Journal replay keeps the same payload, key and principal, including after a reply is lost before any receipt arrives. `HostCallJournal.prepare` is the typed minimum caller contract, with separate propose/decide overloads and key-free input. It resolves only after durable persistence. Each journal is bound to project/principal/epoch; trusted call IDs include the host/session namespace. Reusing a call identity with changed kind/payload fails, not a new key. Adapter-private code records validated receipts and recovers incomplete calls on startup; the small interface does not pretend to implement that storage.

On reconnect or context loss, resume journaled incomplete calls before accepting an uncertain mutation. Do not mint a replacement key because a response is absent. A host unable to persist/recover call identity fails its mutation gate. This is at-most-once per persisted intent, not semantic deduplication of separately requested identical work. The curator flags matching payload digests for inspection; it never silently merges them.

Children can inherit the same read/propose principal. There is no per-child confidentiality claim within that principal. `operation` includes that principal's private proposal content and progress. Separate principals cannot read those receipts. Shared reviewed knowledge becomes generally searchable only after publication.

### Curator actor and discovery

The default curator is one dedicated review-agent process, not an ordinary coding session or a human periodically checking a mailbox. Its supervised toolset can list/inspect proposals, read scoped evidence and decide. It cannot spawn children, delegate, run a shell or read arbitrary files. The process runs under a separate OS identity. Its credential file is mode 0600, outside worker-readable paths; the supervisor injects credentials into private tool execution, never prompts, tool results or worker environments/MCP configs. These are deployment conditions, not assumptions of host inheritance. Worker and curator principals are distinct. The server denies propose for curator credentials and denies deciding on a proposal authored by that principal, including callers bypassing client types. `Curator` exposes read/review operations but not propose. The authority database, backups and private index/credential files belong to the service/curator OS identity and are not worker-readable.

`pendingProposals` lists unresolved entries with pending/blocked states. It uses a bounded keyset cursor tied to project/epoch and a scan cutoff, default 20 and maximum 100 items. The curator selects only pending entries for full review. Finish a bounded metadata scan first and reject discovered blocked entries under the default housekeeping policy, using their recorded reasons and no body/review digest. Then start long reviews; restart discovery afterward so new work is not skipped. This is terminal rejection, not automatic requeue or publication. The durable queue wakes the curator immediately. Default unresolved backlog cap is 100 per project, counting pending and blocked; enforce it transactionally and reject excess submissions before acceptance. Rejection frees a slot but never drops accepted text or history. Terminal records do not occupy unresolved slots; disk/storage capacity remains separately bounded by the G0 profile and returns capacity without pruning acknowledged data. Each selected review has a 150-second deadline and at most one infrastructure retry, then an explicit blocked outcome. The next metadata sweep can reject it without repeating the failed model task. No automatic loop retries blocked work. An unavailable curator is an observable service outage, not a claim of unlimited admission or automatic recovery.

The release profile measures queue wait and decision latency under load. Host sharing smoke tests require the running curator to finish the parent/child example within its 150-second task deadline; mere proposal acceptance does not satisfy sharing. No autonomous trust promotion means capture/recall/hooks cannot publish; audited, policy-bound curator review is allowed without a human checkpoint. The curator is still a fallible reviewer, not a proof of truth or immunity to prompt injection.

### Evidence visibility

Proposal capture stores private evidence only. It does not enter public FTS, QMD, recall or exports. Pending/rejected/blocked text is readable only by its creating principal and the curator, including exact citation reads. Recall sources must be cited by a currently active published page at the pinned snapshot. Publication updates public eligibility and FTS atomically; replacement/retirement removes no-longer-eligible search entries. An already public source stays eligible through its other active references.

Exact historical citations to previously published material remain project-readable and explicitly historical. That exception never exposes a source that was only pending or rejected. `ExactRead` distinguishes private evidence from public `Passage`, so private reads cannot enter recall results through the public type.

## Retrieval and evidence

Default backend: QMD 2.8.3 behind one private adapter, because its vector and explicit fusion modes have the strongest local evidence. QMD is replaceable. Use the existing approved cached embedding only for authorized research. Production needs verified weight terms, a pinned hash and a fresh model-specific benchmark.

Do not download expansion or reranking models implicitly. Use two candidate branches: transactional FTS5 OR-term/identifier search and QMD vector search, with rank fusion and no reranker. Reuse QMD indexing/chunking/embeddings and keep ranking inside retrieval. Remove the separate QMD lexical and pending-tail scans. This smaller configuration needs its own frozen benchmark; it does not inherit the earlier fusion score. Fuse ranks, not incomparable raw scores.

FTS5 indexes citable line-span chunks, not a page-only row with an invented snippet. Each row carries project, immutable page/source revision, inclusive LF line bounds and the full-body hash; its text is those complete lines. Freeze chunk-size/boundary parameters at G0. An overlong line remains one span, subject to the response-capacity rule. QMD hits map through their generation manifest to immutable revisions and line spans. Re-read the selected lines from authority before returning either branch; fuse ranks and deduplicate revision/span overlaps, never fabricate citations from vector snippets. Publication updates lexical rows and evidence eligibility atomically.

A recall operation follows this contract:

1. Pin the current immutable per-project QMD generation `G` before acquiring the database snapshot. Retain a generation reference so promotion or cleanup cannot replace it during this recall.
2. In one short SQLite read transaction, capture project revision `R`, current-page/link/evidence-eligibility mappings and FTS candidates across the whole published corpus. FTS runs inside that transaction, not after it. Retain immutable revision references and release the transaction before model work. If `G` has another project/epoch or a sequence greater than `R`, discard it as unusable.
3. Query only the pinned `G`. Combine its results with the already captured FTS candidates. Revalidate every hit against the authorized snapshot's page revision, active state and evidence eligibility. Do not switch to a newer generation midway through the request.
4. Expand one hop through snapshot-pinned links. Authorize every expanded target again, including evidence. Require the same project and the page head/active state at `R`. Label historical evidence explicitly; never present a superseded linked page as current. Do not force summary or taxonomy routing before retrieval.
5. Deduplicate by revision/span. Select diverse passages within the byte limit. Preserve exact source lines and hashes. The host separately reserves model context space for its serialized tool wrapper and other messages.
6. Return candidates, snapshot identity and coverage as of `R`. A nonempty result does not establish that the answer is supported. Empty results mean no matches under this search, not proof that a fact does not exist.

Reject mutation requests above 262,144 serialized UTF-8 bytes before accepting any captures or proposals. Default/hard recall response cap: 24,000 UTF-8 bytes of compact serialized `RecallResult` JSON, including citations and freshness metadata. `maxBytes` can lower it to a validated minimum of 2,048. Measure the emitted domain JSON bytes, not a guessed tokenizer or only passage text. This is not a token guarantee. Full-page reads are separate, capped at 32,768 body bytes and never silently truncated; larger inputs fail capacity before acceptance. Preflight the complete curator request before proposal acceptance. If accepted work becomes unreviewable after a profile change, block it for metadata rejection rather than partly reviewing it. Proposed candidate cap: 40 per branch, 10 returned passages. Freeze these values at G0. Never truncate a citation away from its passage. If no supported passage fits a valid response budget, return capacity, not a misleading no-matches result.

Default recall returns `best-available` context. If `G` matches `R`, label `hybrid-current`. If its same-epoch sequence is lower, label `hybrid-stale`: semantic search covers only indexed revisions while FTS searches all current published material. A newly published paraphrased fact can still be missed. With no usable vectors, label `lexical-only`. Coverage labels describe searched data, never recall completeness. There is no tail-scan or incomplete mode.

`require-hybrid-current` is opt-in. It returns `not-ready` on index lag/model absence without silently changing its pinned snapshot or downgrading. Degraded context always needs passage-level support and never justifies an absence claim.

The answering-agent policy is explicit: inspect cited passages, support each factual claim, resolve current versus superseded decisions, and abstain when evidence is missing or conflicting. Index scores are not calibrated truth probabilities. Agent-level evaluation tests this policy separately from retrieval recall.

### Index lifecycle

The database outbox names a target project/epoch/sequence. Export only eligible published documents and a hash manifest for that target. Build QMD in a new immutable generation directory, validate counts/model identity, then publish one generation pointer. Upstream's fixed-path previous/current swap is not reader-pinned multi-generation support. Reuse compatible mirror/lock/recovery pieces, not that assumption.

Reader access exposes search/close only, never update/embed, and must leave pinned files unchanged. Do not assume QMD has an unsupported read-only-open option. G2 probes actual provider opens/queries and file hashes; if they mutate a pinned generation, block that integration until a supported read-only path or reviewed upstream patch passes. Do not edit QMD's private tables.

Record the highest indexed target only after promotion succeeds. Never advance it to a newer database sequence merely because that sequence exists. Each manifest binds the project and authority identity. A crash replays the outbox idempotently. Keep the last valid generation while rebuilding. Queries acquire a generation reference before their SQLite snapshot and retain it until finished; garbage collection must not delete pinned generations. Promotion and reference acquisition share a short service-owned critical section, not a lock held during model work.

No model/index state is authoritative. Deleting indexes and exports must not delete accepted knowledge. Superseded revisions remain readable through exact citations but do not appear as current decisions.

## Reuse plan

| Existing project | Reuse | New gap or limit |
|---|---|---|
| Pi LLM Wiki 0.12.5, MIT | OKF/document parsing, citation/source conventions, MCP schemas and useful Pi integration. Adapt its QMD adapter/index recovery. | Do not expose its direct capture/retro writes to parallel clients. Its installed internals are not a stable public library API. Pin an extraction/fork and preserve notices. |
| QMD 2.8.3, MIT code | Indexing, embeddings, lexical/vector retrieval and rank fusion | Consume derived project documents. Do not edit QMD's private database tables. Model licensing is separate. |
| SQLite and FTS5 | Transactions, constraints, durable receipts and exact/lexical search | A small curation schema is necessary. Do not build a new database or embedding engine. |
| Official MCP SDK, installed with Pi Wiki | Protocol and transport | Application authorization is enforced separately from tool annotations. Reuse stdio support and add shared HTTP access only through supported SDK transports. |
| MCP Memory Service 12.7.0, Apache-2.0 | First prototype's bounded upstream-fit check | Adopt as authority only if real public operations satisfy atomic curation, project isolation, retries and provenance. Current source review does not establish that. |
| nvk/llm-wiki and newsroom, MIT | Optional read/review workflow ideas | No second session-memory mechanism or copied framework is needed. |

Use installed components for experiments. Production dependencies need a reproducible lockfile, original notices and a vulnerability/license check. Do not copy restricted redmizt code. Do not claim project popularity or maintenance quality without dated evidence.

## Security and operations

- Bind project and role to authenticated connection credentials, not a model-supplied project argument or cwd. No cross-project recall by default.
- Ordinary sessions and their children receive read/propose access, possibly under the same worker principal. Only the isolated non-delegating curator process holds publish authority. Test worker and attempted curator-child inheritance, not only a low-privilege parent's children.
- First deployment has one trusted worker OS account plus the isolated service/curator OS identity. Trust the administrator and child-launching supervisor. No confidentiality between processes sharing the worker account is claimed; curator secrets and authority files are isolated from that account. Broader hostile-worker or administrator isolation requires a separately approved sandbox/threat model, not more prompt instructions.
- Bind HTTP to loopback initially. If enabled, validate Host and Origin, disable wildcard CORS and use scoped credentials. LAN/remote access requires TLS and a separately verified authentication setup. Do not change existing LAN services.
- Use one long-lived service identity. If a host only supports stdio, its gateway connects to that service. Do not launch an independent publisher per client.
- Accept bounded UTF-8 source text initially. Do not expose arbitrary filesystem reads, shell execution, recursive crawling or URL fetching. A later importer needs path/symlink containment, SSRF controls and its own gate.
- Treat source text as untrusted data. Its instructions cannot grant roles, trigger tools or promote claims into project rules. Give raw sources and reviewed pages distinct labels.
- Log operation IDs, durations, conflict counts, index lag and denied scopes. Do not log credentials or full prompts/source bodies by default.
- Back up authority with SQLite's backup API and a versioned manifest. Do not copy only the live `.db` while ignoring WAL. Test restore, hashes and exact citations. Derived indexes can rebuild afterward.
- Preserve cited revisions under the documented retention policy. Normal retirement is a tombstone, not erasure. Legal deletion requires a separate approved purge procedure covering backups and exports; do not pretend tombstones erase secrets.

## Non-goals and redesign triggers

No five-domain taxonomy, new orchestrator, autonomous trust promotion, distributed consensus, hosted embedding dependency or simultaneous four-host rollout.

Two recurring workarounds for the same invariant trigger redesign. Examples include direct filesystem edits becoming authority, manual repair of accepted operations or host-specific storage forks. Prefer removing a component before adding another coordinator. [The delivery plan](DELIVERY.md) limits that redesign and stops work when its budget expires.

Verification for this artifact: `python3 specs/wiki-system/verify.py`. This checks contract/document structure, not runtime correctness.
