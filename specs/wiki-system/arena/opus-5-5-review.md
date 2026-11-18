# Independent architecture review: shared coding-agent knowledge design

## Verdict: NEEDS-REVISION

This is not a production certification. No runtime evidence exists for G0–G8. The core shape is sound and mostly reuses existing components: one SQLite authority, immutable proposals, curator CAS publication, and QMD as a derived, replaceable index. Three gaps in the contract and roles should be fixed before P1 writes migrations. Each fix is small. None of them argues for a different architecture.

## Ranked findings

### 1. must-fix: no full-page read, so a `replace` can silently drop page content

**Evidence**
- `contract.d.ts`: `Change.replace` carries the full `markdown`.
- `Knowledge.read` only accepts a `Citation`, which is a span plus a `hash`, and returns one `Passage`.
- `recall` returns at most 10 span passages (ARCHITECTURE "Retrieval and evidence", cap of 10 passages).
- No method returns a whole page by `PageId`/`PageRevision`. `Curator.proposal` returns the change but not the base body.

**Scenario**
1. A child recalls lines 10–20 of `token-rotation` at revision r7.
2. It proposes `replace` with base r7, using a markdown body made only from the section it saw.
3. CAS passes because the base still matches the head. The curator approves without seeing r7's full text.
4. The rest of the page is deleted with no conflict.

CAS catches races, not losses inside a single proposal. The usage example (`markdown: correctedExplanation`) invites exactly this.

**Smallest correction**
- Add `page({ page, revision? }) → { revision, title, markdown, active }`.
- Let the curator view the base page body next to the proposal.
- Add a G1 case: a replacement built from a partial read must be visible to the reviewer as a deletion.

### 2. must-fix: who the curator is, and how the curator finds proposals, is undefined

**Evidence**
- The curator is always "a separate authorized curator" (ARCHITECTURE usage; "Security and operations").
- G4 step 1 says only "A curator accepts it."
- `Curator` has `proposal({id})` but no way to list pending proposals. A curator can only learn IDs if proposers pass them along outside the system.
- "No autonomous trust promotion" is a stated non-goal.

**Scenario A: authority inheritance**
If the curator is an agent session in Claude Code or Codex, the children of that session normally inherit its MCP configuration and credential. Those children can then publish. G4 step 5 ("unauthorized child publication must fail") passes if it is only tested from a non-curator parent, so the gate can be met while the boundary is broken.

**Scenario B: sharing latency**
A child proposes a finding. The parent cannot recall it, and cannot call `proposal()`, until a curator publishes it. If the curator is a human, or a separate session that runs occasionally, parent/child sharing inside one task does not happen through the knowledge service. That weakens the stated requirement. With eight proposers and one curator, there is no rule for how large the backlog may grow.

**Scenario C: prompt injection aimed at the curator**
If the curator is a model, injected source text inside a proposal targets the one principal that can publish. G3's injection tests name "the agent", not the curator.

**Smallest correction**
- State the curator's actor and placement: a human CLI, or a dedicated agent profile whose host config is never inherited by worker sessions or their children.
- State where the curator credential lives (outside any file or env readable by worker sessions).
- Add `pendingProposals({ cursor })` to `Curator`.
- Decide whether proposers can see their own pending proposals through `operation(key)`. Today it returns state but not content.
- Add curator-session children and curator-targeted injection to G3/G4.

### 3. must-fix: `ProjectRevision` and IDs have no epoch across a restore

**Evidence**
- `ProjectRevision = Brand<number>`.
- `atLeast` is for read-your-write, and "If the restored service cannot meet it, return an explicit availability error" (ARCHITECTURE "Proposal and publication state machine", final paragraph).
- G3 already accepts a nonzero RPO after a restore.
- Index manifests carry an "authority identity", but nothing the client sends does.

**Scenario**
1. A client's write commits at R=120.
2. The disk fails, and the service restores a backup taken at R=100.
3. After 20 new commits, R=120 again. A recall with `atLeast: 120` is now accepted even though the client's write is gone.
4. If proposal or revision IDs are sequential, an old receipt or a citation held in a transcript can now point to different content.
   - Citation hashes would detect this for citations.
   - `ProposalId` lookups would not detect it.

**Smallest correction**
- Make the revision `{ epoch, seq }`, with a new epoch on every restore.
- Reject `atLeast` values from an older epoch with an explicit error.
- Require proposal and revision IDs that are never reused (random or epoch-scoped).
- Test this in G3 restore.

### 4. should-fix: the token budget relies on a tokenizer the service cannot know

**Evidence**
- "using the tokenizer of the consuming model" (ARCHITECTURE retrieval step 5).
- G2: "Within the frozen token cap".
- `RecallInput` has no budget or tokenizer field. The four hosts use different models.

**Scenario**
The service counts tokens with an assumed tokenizer. A host with a different tokenizer receives more than 6,000 tokens, so the G2 gate can't be checked consistently.

**Smallest correction**
- Either add `maxTokens` and a fixed, conservative estimator that the contract names, or define the cap in bytes.
- Measure G2 with that same estimator.

### 5. should-fix: retry-key ownership and the principal model are unspecified

**Evidence**
- `ProposalInput.key` is a field the model fills in.
- "Poll `operation(receipt.key)` after a lost reply. Never mint a new retry key" (usage).
- Keys are scoped to the project and principal.
- Whether a child gets its own principal or shares the parent's credential depends on the host. The design claims a child gets "its own MCP connection and read/propose credential", which many hosts' config inheritance may not allow.

**Scenarios**
- Two agents under a shared principal pick the same key, such as `fix-token-1`, and get a `key-reuse` error on legitimate, distinct work.
- A model that lost its context after a lost reply mints a new key and creates a duplicate proposal.
- Duplicate proposals are low-harm because nothing is published without review. The guarantee is still overstated.

**Smallest correction**
- Have the MCP or gateway layer generate keys and return them.
- Specify that children may share the parent's principal. Do not promise per-child credentials unless a host proves them in G4–G7.
- Let the curator see when pending proposals have the same payload digest.

### 6. should-fix: defaulting to `require-hybrid-current` will usually return `not-ready`

**Evidence**
- `not-ready` is returned whenever G < R (ARCHITECTURE retrieval section).
- The proposed visibility budget is ≤30 s p95 (G2).
- Eight proposers plus active curation keep G < R much of the time.
- `not-ready` returns no passages and defines no bounded wait.
- The usage example already passes `allow-degraded`.

**Scenario**
Callers learn to always pass `allow-degraded`. The strict default then protects nobody and adds a round trip.

**Smallest correction**
- Pick one:
  - Add a bounded `waitMs`, used together with `atLeast`.
  - Make the labeled best-available result the default and make strict mode opt-in.
- Keep the rule that degraded results never justify an absence claim.

### 7. should-fix: whether pending or rejected evidence is visible in recall is undefined

**Evidence**
- Proposal acceptance commits the captured text (state machine step 1).
- `Passage` includes `source-evidence`.
- The outbox is only enqueued at publication (step 5).
- Nothing says whether captures from pending or rejected proposals are in the authority's FTS, or readable by any project reader.

**Scenario**
A child captures injected text. If its FTS entry is written at proposal time, the text reaches every agent's recall before the curator ever sees it. That bypasses review for evidence.

**Smallest correction**
- State that recall only searches evidence cited by published revisions.
- Limit pending or rejected captures to the proposer's own `operation` lookups and to curator inspection.

### 8. should-fix: the budget and gate scope don't fit together

**Evidence**
- G0 requires 200+50 stratified questions, a separate reviewer for ambiguous cases, and frozen gold evidence.
- P0 is limited to "One working day, two candidate runs" (DELIVERY "Execution limits").
- The per-unit maximums add up to more than the 12-day total before any redesign or G8: 1 + 5 + 4×2 = 14 days.
- The G2 answer gate (≥90%) does not say which host or model, even though answer quality depends on the model.

**Scenario**
The corpus gets built in a hurry or shrinks quietly, which undermines the most important recall evidence. Alternatively, OpenCode is cut off by the overall budget rather than by a gate result.

**Smallest correction**
- Give corpus construction its own budget line.
- State that the 12-day total may end the rollout before OpenCode.
- Name the model used for G2 answers, and re-run a small answer subset for each host.

### 9. consider: smaller clarifications

- **Simplify the lexical branches.** The authority's FTS5 is transactional and always current, so the "pending-tail scan", `incomplete` and `scan-budget` look redundant. Using FTS5 as the only lexical branch and QMD only for vectors removes one coverage mode and the QMD lex branch, which measured 34% on the initial suite (research README).
- **Conflict terminality.** Say whether `conflict` makes the proposal terminal.
- **Retired pages.** Say whether a retired page counts as "absent" for `create`.
- **Citation hashes.** Say whether `Citation.hash` covers the span or the whole revision.
- **Slice sizes.** Set minimum question counts per G2 slice. A 90% threshold on about 10 questions is decided by one miss.
- **Post-hoc profile changes.** Mark any performance-profile revision made after measurement as post-hoc, and have the verifier record it. "revise the deployment profile transparently" otherwise allows relaxing a failed budget.
- **Host stop rule.** Choosing an "explicit alternative deployment profile" for a blocked host needs an owner, because no human checkpoint exists.
- **Pinned QMD generations.** Pi Wiki's swap (`qmd-indexing.ts`: `previous-moved`/`current-promoted` journal over a fixed index path) is not multi-generation with reader references. Pinned generations need separate immutable directories and read-only opens. This is correctly deferred to G2, and ARCHITECTURE already says "adapt, don't copy blindly". The implementer should expect new code here.

## What is already sound

- One `flock`-guarded authority with publication in one `BEGIN IMMEDIATE` transaction (revision, head, decision, receipt, FTS, outbox). This directly fixes the measured losses (23/96 captures, 7/8 same-slug writes).
- An explicit base is required for replace and retire, and omitting it is invalid. A rebase is a new reviewed proposal.
- Idempotency keys are unique across operation kinds, with the operation kind included in the request digest.
- `PageRevision`, `ProjectRevision` and `IndexGeneration` are separate types.
- The index generation is pinned before the SQLite snapshot, and FTS runs inside the read transaction.
- Coverage labels are honest: "empty ≠ absence", scores are not probabilities, and an abstention policy is separate from retrieval recall.
- The trust boundary is stated plainly (same OS user is out of scope). Tool annotations are not treated as authorization.
- Backup uses the SQLite backup API. Rollback must not drop commits made after the backup.
- Hosts are gated in sequence, a fresh CLI is never relabeled as a child, and the required `pi-subagents` test replaces the earlier `runSubAgent` test.
- Iteration limits are bounded, holdout thresholds are frozen, and G8 requires the verifier to run the checks itself. Unrunnable safety checks count as blockers.
- MCP Memory Service gets one bounded fit test before any custom coordinator. That is the right check on whether the design is too bespoke.

**Delete or simplify:** the redundant tail-scan branch (see 9). Nothing else looks like unnecessary infrastructure. The custom schema is about the smallest one that can give the required CAS and replay guarantees. A git-ref-based authority would be a possible alternative but brings its own receipt and FTS problems, and I did not evaluate it further.

## Checks performed, unknowns, and checks not performed

**Performed (read-only)**
- Read ARCHITECTURE.md, contract.d.ts, DELIVERY.md and GROUNDING.md end to end.
- Read research/README.md, and RATIONALE.md after forming my own assessment.
- Read the first 250 lines of the installed Pi LLM Wiki `extensions/llm-wiki/lib/qmd-indexing.ts`, to check how its lock and swap work.
- Each finding above was checked against the contract types and the prose.

**Not performed**
- No code, gates, benchmarks, host CLIs, `verify.py`, or QMD/MCP Memory Service source beyond the file above.
- I did not check QMD's handling of multiple store files.
- I did not read arena/ or other reviews.

**Unknowns**
- Real corpus size, hardware and SLOs.
- The license of the embedding weights.
- Whether each host's child mechanism keeps MCP tools and can scope credentials per child.
- Codex CLI 0.163's child support.
- The OpenCode 1.19.3 schema.
- Whether a ≤30 s visibility time and ≥95% recall@10 are reachable on real data.

All of these are runtime questions for the gates, not settled facts.
