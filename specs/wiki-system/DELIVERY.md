# Bounded delivery and acceptance

This is a proposed execution plan, not completed work. The current deliverable is the design and contract. Start implementation with P0. Do not mark production ready from document checks.

## Scope and defaults

First release: one local service, a transactional curated knowledge store, hybrid retrieval, stable citations, read/propose clients and a separately authorized curator. Deploy host support strictly as Pi -> Codex CLI -> Claude Code -> OpenCode.

Unknowns include real corpus size, hardware, retention policy, remote access and production SLOs. P0 records them in a deployment profile. If no additional requirements arrive, use these reversible prototype defaults:

- One trusted worker OS account plus a separate service/curator OS identity, local filesystem, loopback service and explicit project/role credentials. Workers cannot read the authority or curator secrets.
- UTF-8 text evidence, reviewed pages, no crawler or public endpoint.
- Eight concurrent proposers, ten concurrent readers, no simultaneous publishers outside the service.
- Up to 10,000 documents and 100,000 chunks as a capacity test ceiling, not a demonstrated limit.
- Approved local embeddings. Expansion and reranking remain disabled until evidence justifies their cost.

Do not silently reduce the profile to make tests pass. A deployment beyond this profile needs another capacity/security gate.

## Execution limits

An iteration means implementation, the frozen gate run, a recorded result and one decision. Retrying the same failing command without a new hypothesis consumes another iteration.

| Work | Hard limit | On exhaustion |
|---|---|---|
| P0 upstream-fit research | One working day, two candidate runs | Choose the contract-compatible existing stack or record a blocker. Do not keep adding candidates. |
| P0 corpus construction/labeling | Two working days, one ambiguity-review pass | Stop G0 if the representative split cannot be built. Do not shrink it to pass. |
| Core prototype P1-P3 | Three build/test iterations, at most five working days | One redesign is allowed only for a repeated architectural fault. |
| Redesign | One design revision and one build/test iteration | Stop with reproducible blockers if the gate remains red. |
| Each host P4-P7 | Two repair/retest cycles, at most two working days | Mark that host blocked. Do not advance to the next host. |
| Independent final review | One review, one correction cycle, one rerun | Fail the release if a blocker remains. |

Total release budget: twelve working days by default. It overrides the per-unit ceilings, which are not additive allocations. The budget can end rollout before OpenCode or before any host passes. Stop at the global cap and preserve the blocked/untested statuses. Only the project owner can authorize a new budget or smaller release scope. No human checkpoint is needed inside the approved scope. Run no unbounded autonomous loop.

Each local command gets a deadline. Proposed ceilings: ten minutes per core gate suite, 150 seconds per agent task, one retry only for a classified transient infrastructure error. Record all failed attempts. Count retries in the iteration budget.

No model downloads or new services start implicitly. Declare size, license, resource needs and purpose before a model download. Preserve live access, user credentials, existing services and global host configuration.

## Implementation units

| Unit | Smallest useful result | Gate and evidence |
|---|---|---|
| P0, baseline and fit | Clean isolated workspace, pinned versions/notices, deployment and answer-model profiles, separately budgeted corpus/labels and frozen eval split. Probe MCP Memory Service's real operations before a custom coordinator. | G0, explicit reuse decision and source/runtime receipts |
| P1, durable core | Migrations, proposal capture, immutable revisions, curator CAS, idempotency receipts, transactional FTS/outbox and exact citation reads | G1, actual process races and crash/restart tests |
| P2, derived retrieval | Reuse/adapt QMD indexing, project manifests, rank fusion, freshness reporting, bounded context and current-revision checks | G2, raw rankings, held-out metrics, freshness/rebuild evidence |
| P3, service boundary | Official MCP transport, scoped authentication, tool allowlists, no arbitrary file/URL access, backup/restore | G3, adversarial requests and restore receipts |
| P4, Pi | Project-local connection, answering instructions and actual deployed child tool access | G4, parent/child/fresh-session traces |
| P5, Codex CLI | Only its version-checked configuration and child fixture | G5, same contract through the real CLI |
| P6, Claude Code | Only its configuration, foreground/background child policy and fixture | G6, same contract through real children |
| P7, OpenCode | Installed-schema validation before config generation, actual native-child fixture | G7, same contract through the real host |
| P8, release | Independent verification, tested rollback, sanitized artifact and operator runbook | G8, SHA-bound verifier receipt and no open release blockers |

P0 checks whether MCP Memory Service can satisfy durable proposals, digest-bound review, same-page CAS, replay receipts, scoped citations and project authorization together. Metadata tags and database locks alone do not pass. If public operations cannot provide those invariants, retain the chosen SQLite authority and reuse QMD/MCP/wiki-format code. Do not fork a larger memory service merely to hide a second custom authority inside it.

Implement vertical slices. P1 first proves propose -> review -> commit -> restart -> exact read before any host UI work. P2 then adds real retrieval to that same path. Generate exports from the authority; do not add file watchers that promote manual export edits.

## Gate G0, baseline and evaluation design

Use an isolated worktree/workspace without modifying live services. Establish a clean test baseline and pin code, models, client versions and schemas. Current Git history must not become a public remote. Release from clean sanitized history.

Build a representative corpus with permission to use it. Keep evaluation questions and gold evidence outside all indexed content and agent workspaces. Include realistic code, decisions, procedures and superseded facts. Never send private project text to an unapproved model endpoint.

Proposed minimum: 200 answerable questions plus 50 missing/conflicting-fact controls. Reserve 40 percent for development and 60 percent for held-out evaluation. Stratify before splitting. Include exact identifiers, paraphrases, Ukrainian-to-English queries, multi-page answers, current/superseded decisions, child-written facts and cross-project lookalikes. Each measured hard slice needs at least 30 held-out positives; record overlaps. Report counts and interval estimates rather than treating a small percentage as precise.

Freeze corpus versions, gold source revisions, questions, parameters and thresholds before optimization. Have a separate reviewer label ambiguous cases. Do not tune against held-out individual answers. The final verifier can add an unseen adversarial set and must record it separately. Report sample counts and uncertainty; a percentage alone is not a production guarantee.

The earlier 24-document suites remain regression fixtures. They are not a fresh holdout or proof of scale.

Baseline G2 answer profile: the previously used local `qwen3.8-35b-a3b-mtp-32k`, thinking off. At G0, pin its actual provider/model revision, inference parameters, prompts and approved endpoint. Confirm it is available; otherwise block and explicitly replace the profile before evaluation. The curator uses a separately isolated profile with the same approved model initially. Freeze its full-request input budget, fixed policy/tool wrappers, output reserve and a pinned tokenizer or validated conservative counting bound. An unverified counter blocks G0. Freeze unresolved/storage capacity separately; known oversized review bundles must fail before any proposal/capture is accepted. Never send private corpus text to an unapproved provider. G2's headless answer harness is not proof of any CLI's behavior.

## Gate G1, authority and concurrency

Test the actual public service calls and persisted rows, not only helper functions.

- Eight independent processes submit 96 distinct evidence/proposal operations. All acknowledged proposals and source snapshots survive restart with matching hashes.
- Eight proposals target one page/base. All proposals survive. Exactly one competing publication succeeds. Others return explicit conflicts, with no silent overwrite.
- Repeated identical requests return the same proposal/revision. Reused keys with changed payloads or different operation kinds fail. Test interrupted proposal and decision replies under the same principal. Lookup must remain unambiguous. Different principals cannot read one another's receipts; curator proposal inspection never reveals a proposer's key.
- Kill the service at named boundaries before commit, after commit before reply, and before/after index promotion. Restart and retry. Verify receipts, heads, FTS and outbox from durable state.
- Test concurrent decisions on one proposal, stale review-bundle digests, create-on-existing, replacement without base, contradictory terminal decisions and a reviewed rebase. Conflict is terminal; retired PageIds are not absent.
- Fetch a whole page, then construct a partial replacement from a recalled span. Curator inspection must include the entire base, complete replacement and all removed lines. An omitted/truncated base or diff cannot count as review. Test full-page capacity and context-blocked review without silent truncation.
- Crash the trusted adapter before send, after send and after commit/before receipt. Recover its durable host-call journal, replay the same key/payload and preserve principal binding. Two workers sharing one principal need distinct keys. Missing durable call identity blocks mutation support, not a claim of guaranteed semantic deduplication.
- Fill the 100-slot unresolved backlog with accepted work forced into blocked states after admission, such as timeouts or a changed review profile. The 101st proposal must fail capacity without accepted captures. An authorized metadata-only rejection must work without a review digest or reading the body, durably free its slot, and permit one new proposal. Run the default metadata sweep to clear the remaining blocked entries before long reviews. Restart and verify every original proposal, evidence hash, reason and receipt survives; rejection must not advance publication heads/sequence or alter public search eligibility.
- Exercise every state-table row, including pending rejection, blocked publication denial, publish-versus-block/reject races, identical terminal retries and contradictory decisions. Reject known oversized full review bundles before acceptance. Check the frozen counter includes the base, proposed body, diff, evidence, wrappers and output reserve. Reject or block, never silently truncate.
- Exercise SQLITE_BUSY, disk-full/error injection and cancellation. No false success receipt, half-published revision or missing accepted source is allowed.

The two blocked-queue cases distinguish known oversize admission rejection from later review failure. They must execute against the real service when P1 exists; the current type tests and document checker are not substitutes.

Required result: zero lost acknowledged operations, zero silent same-page overwrites and zero duplicate logical publications in the tested schedules. State the limits of stress runs and fault injection. Do not claim proof for every interleaving or power failure.

## Gate G2, recall and answers

These are proposed release thresholds. Freeze or explicitly revise them at G0, before viewing holdout outcomes.

| Measurement | Proposed gate |
|---|---|
| Evidence recall@10, macro across positive questions | At least 95 percent |
| All-required-evidence@10 for multi-page questions | At least 90 percent |
| Hard paraphrase and cross-language slice recall@10 | At least 90 percent each |
| Agent answers correct and supported | At least 90 percent on answerable holdout |
| Exact citation revision/hash/span resolution | 100 percent |
| Unsupported confident answers on negative/conflict controls | At most 5 percent |
| Cross-project disclosures and superseded facts presented as current | Zero |
| Returned context size | At most the frozen UTF-8 JSON byte cap, citations and metadata included |

Verify lexical chunk rows resolve their immutable revision, full-body hash and complete LF line span, including evidence chunks and an overlong single line. QMD chunk mappings must resolve through the pinned manifest to the same authority citation system. Branch fusion may not return a fabricated snippet or stale revision.

Score retrieval and answers separately. Assess citations for support, not merely existence. Include false matches from vector search. Every abstention must distinguish missing evidence, conflicting evidence and degraded search.

Proposed performance budgets on the recorded deployment machine: warm recall p95 <=2 seconds, committed-to-hybrid visibility p95 <=30 seconds, service peak RSS <=2 GiB. Measure cold start, indexing and embedding separately. Use at least 100 timed queries, ten concurrent readers and an overlapping write run. Record corpus size, machine, model, queue wait, curator decision latency and failures.

The byte gate measures compact emitted `RecallResult` JSON, including citation/freshness fields. Test ASCII, Ukrainian, emoji, JSON escaping and an overlong single line with default 24,000-byte and lower requested limits. If no passage fits, require capacity rather than a false no-matches result. Host adapters separately budget their actual model's tool-message tokens. Do not relabel bytes as a token guarantee.

Any profile/threshold revision after measurement is post-hoc. Preserve the original failed result, obtain project-owner approval and rerun the affected gate with a new frozen profile and independent evidence. Changing a target does not turn the old failure into a pass. No automatic budget relaxation is allowed.

Disable embeddings, remove an index, lag the outbox and kill an index worker. Check best-available `lexical-only`/`hybrid-stale`, plus opt-in strict `not-ready`. Add a relevant paraphrased page after the indexed generation; current FTS does not imply full semantic coverage or absence. Publish and promote between generation pinning, SQLite snapshot acquisition and vector search. FTS candidates must remain bound to that snapshot, and no pinned generation can be deleted, replaced or mutated mid-query. Hash actual generation files before/after supported provider opens and queries; do not assume a nonexistent QMD read-only option. Rebuild from authority and compare retrieved revision IDs. A stale or wrong-epoch generation must never claim `hybrid-current`.

Add reranking, expansion, hierarchical summaries or a new backend only after one measured failure justifies the experiment. Limit tuning to two retrieval configurations plus one approved embedding model. Reject a change that improves recall by breaking isolation, provenance or resource limits.

## Gate G3, security and operations

Verify project/role denials on every operation, including exact citation reads, proposals, operation lookups and exports. Deny curator proposal submission and self-approval at the server even with forged/raw MCP calls. Attempt metadata rejection as a worker and across projects; neither may release queue slots. Verify authorized blocked rejection remains usable with a full backlog and an unavailable review model. Use lookalike page IDs across projects and forged tool arguments. Test one-hop links to another project and to retired/superseded pages. Expansion must repeat project, snapshot and active-state checks. Tool annotations are not authorization.

Inject source text that asks workers and the privileged curator to reveal credentials, switch projects, run a shell, delegate or publish unsupported claims. It must remain quoted evidence. Test curator-targeted proposal injection and its service-enforced tool limits. Attempt worker access to curator files/environment/configuration under the actual OS identities. Attempt curator child creation; its supervisor must deny it. Do not call the model a proven injection-proof reviewer.

Capture pending/rejected/blocked evidence containing a unique marker. Another principal must not see it through recall, FTS/QMD mirrors, exports or forged exact citations. The owner can inspect its own operation snapshot and private source. Publish a cited source and verify visibility only through an active reviewed page; replace/retire its last active reference and recheck search eligibility. Test input limits, malicious Markdown links and path traversal. The first release has no URL fetcher or file importer.

For HTTP, test authentication, Host/Origin handling, malformed requests, cancellation and connection recovery. A second service process must not create another uncontrolled publisher or concurrent QMD mutator.

Back up during writes through the supported SQLite API. Restore into a clean instance with a fresh epoch, check authority hashes and retained exact historical citations, then rebuild indexes. Save a barrier after backup, lose that commit, restore and advance to the same numeric sequence. The old `atLeast` must still return stale-epoch. Retained immutable IDs must resolve the original content; lost server-generated revision/source/proposal/operation IDs must return not-found, never alias new content. A client-chosen PageId for a lost post-backup create may be created again, but its old exact revision/hash citation must still return not-found; a retained retired PageId remains occupied. Old journaled mutations cannot replay under a fresh key automatically. Old review attestations must fail; restored pending proposals need fresh review. With no intervening writes, the new-epoch bootstrap rebuild must still make strict retrieval ready.

The proposed backup interval is five minutes. The release profile must state RPO and measured RTO. RPO is zero only for acknowledged writes on the surviving authority, not for a destroyed disk restored from an older backup.

Rollback must preserve accepted knowledge. Retain the prior application and backup. Test schema compatibility before downgrade. If old code cannot read the new schema, use maintenance/read-only mode and an explicit migration, not a blind database restore that drops post-backup commits.

## Gates G4-G7, actual coding hosts

Run these steps with synthetic nonce facts first, then approved representative tasks:

1. Start the isolated running curator and session A with normal read/propose configuration. Search and propose a fact. Observe pending-list discovery and a reviewed terminal decision within the 150-second smoke-task deadline. Mere proposal acceptance is not sharing.
2. End A. Start an independent session B from another worktree. Retrieve the fact, current revision and original source without a transcript pasted into its prompt.
3. Launch the host's actual deployed child mechanism. Assert the child can see and call the read/propose tools, rather than trusting a parent summary or tool listing.
4. Have the child read the parent fact and propose a derived fact with source provenance. Accept it. Read it from B or another fresh session.
5. Restart the service and host. Repeat exact citation resolution. Attempt a cross-project read and unauthorized child publication; both must fail. Worker children can share their parent's read/propose principal. The curator must have no inheritable worker-host config or child capability.
6. Test host approval modes, timeouts, tool filters, lost-reply journal recovery and unavailable-service behavior. Save receipts and inspect durable state. Run at least 30 answerable and 10 negative/conflicting subset questions through each actual host/model, including hard-language and multi-page cases. Pin that host's model/profile and apply the answer/support/citation gates; do not inherit the G2 model's score.

Pi must test the separate `pi-subagents` extension actually intended for use. The prior installed wiki `runSubAgent` experiment does not satisfy that gate. SDK test runners need explicit MCP extension binding/tool activation.

Codex must test the installed CLI's actual child feature and applicable MCP settings. Claude must test foreground and background children if both are supported in the deployment profile. OpenCode must validate installed 1.19.3 rather than blindly adopting current V2 documentation.

If a host lacks native child support, do not relabel a fresh CLI as its child. Record unsupported behavior and stop advancement. Only the project owner can approve an alternative release scope/profile; otherwise the host remains blocked and later hosts remain untested. Passing Pi does not imply passing another host.

## Gate G8, independent final agent

Freeze the release commit, dependency lock, corpus/model hashes, deployment profile and gate commands. Use a fresh verifier session with no implementer conversation. Give it the requirements, public tools, approved corpus and artifact locations, not a success narrative or hidden gold in its workspace.

The verifier must run, not merely read, the gate. It checks all released hosts, same-page races, replay after an interrupted reply, stale vectors, exact citations, authorization, restart, backup restore and rollback. It inspects raw traces and durable counts itself. A final report names the tested SHA, commands, exits, failures, evidence hashes and remaining manual checks.

An unexecutable safety-critical scenario is a blocker, not a pass. Permit one correction cycle and rerun affected gates plus core regressions. Persist unresolved failures and stop after that budget.

Release only when all in-scope gates pass. Mark each host explicitly as untested, blocked or verified. Do not call the whole system production ready while later hosts or data-safety gates remain unverified.

## Current verification

`python3 specs/wiki-system/verify.py` checks these design artifacts and evidence links. It does not execute G0-G8. Implementation has not started.
