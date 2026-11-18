## Verdict: READY-FOR-IMPLEMENTATION

This verdict covers the design only. No service, simulator or host integration exists. G0–G8 have not run and must all pass before production. G1 and G3 describe runtime proof that is planned, not done.

## Resolution table

| Item | Status | Evidence (current bytes) |
|---|---|---|
| **M1: blocked backlog wedges admission** | **Resolved at design level** | See the M1 notes below. |
| **V1: a contradictory report could pass as READY** | **Resolved** | See the V1 notes below. |
| **S1: worker vs curator OS identity** | Resolved | DELIVERY "Scope and defaults" now says "One trusted worker OS account plus a separate service/curator OS identity… Workers cannot read the authority or curator secrets." This matches ARCHITECTURE "Curator actor" and "Security and operations". |
| **S2: typed pre-send journal** | Resolved | `HostCallJournal.prepare` has separate propose and decide overloads. Their input carries no key (`key?: never`), and they return the keyed request only after durable prepare. ARCHITECTURE "Retry ownership" makes the adapter responsible for recovery. Reusing a call ID with a changed payload fails. Two negative tests check that keys cannot be injected. |
| **S3: logical PageId vs immutable revision** | Resolved | A contract comment scopes PageId uniqueness to retained history. ARCHITECTURE "Restore identity" separates client-chosen names from epoch/UUID server IDs. A lost name can be reused, but an old revision/hash citation never resolves to the new content. G3 tests both. |
| **S4: curator self-proposal / self-approval** | Resolved | `Curator` uses `Pick` without `propose`, and the compiler rejects `curator.propose`. The server denies curator propose and deciding one's own proposal "including callers bypassing client types". G3 uses forged MCP calls. |
| **S5: lexical chunks / citation spans** | Resolved | FTS rows are line-span chunks carrying the revision, LF bounds and full-body hash. QMD hits map to the same spans through the manifest. Both branches re-read the lines from the authority. G2 covers mapping and overlong lines. |

**M1 detail**

- **Metadata-only rejection.**
  - `Decision.reject` needs only a reason. `pendingProposals` returns the proposal ID, digest and state, including the blocked reason, without the body.
  - The architecture example calls `decide` using `item.state.reason`. `Curator.decide` says it can reject pending or blocked work without review.
- **Atomic release without publishing.**
  - Step 7 records the decision and receipt and frees the slot in one transaction.
  - The proposal and its evidence are kept.
  - Page heads, FTS, outbox and the publication sequence are untouched.
- **Discovery and drain by default.**
  - The default housekeeping policy runs a bounded metadata sweep and rejects blocked entries before long reviews, then restarts discovery.
  - Blocked outcomes come from the service-owned supervisor, so a review-model outage still drains: work times out, becomes blocked, then gets rejected.
  - G3 requires rejection to work with a full backlog and an unavailable model.
- **Both failure classes are covered.**
  - Known-oversize bundles are preflighted at admission against the G0-frozen counter (step 1, "Retrieval and evidence").
  - Post-admission timeouts and profile changes become `blocked`. G1 states the two cases separately.
- **The state table closes late paths.**
  - Publishing blocked work returns invalid-state.
  - Repeat events after a proposal leaves pending are no-ops.
  - Decided proposals are never mutated.
  - Contradictory decisions return terminal-decision.
  - All transitions serialize in the authority transaction.
- **Storage is honestly bounded.** Terminal records leave the unresolved cap. Disk is bounded separately and returns `capacity` without pruning anything.

**V1 detail**

- **One leading verdict.**
  - `verify.py` requires that the only line starting with `## Verdict:` is the exact READY string. It also requires that line to be the first nonblank line.
  - Conflicting headings in either order, duplicates and fenced or prefixed examples all fail as UNVERIFIED.
- **Earlier checks are kept.**
  - Provider, model, high reasoning and completed status.
  - Report hash.
  - Optional receipt verdict agreement.
  - Path containment.
- **Hash binding covers checker and tests.** `CORE` now includes `verify.py` and both test files, and `test_changed_reviewed_checker_or_tests_are_stale` covers them.
- **The positive control is preserved** by `test_matching_current_snapshot_is_ready`.
- **Count.** There are exactly 17 tests, matching `validation.json`.

**Original guarantees are intact.**

- The full `PageSnapshot` base and diff in `Review`.
- The distinct `ReviewDigest` brand.
- Epoch-scoped barriers and `stale-epoch`.
- Best-available by default, with strict freshness opt-in.
- `private-evidence` kept out of `Passage`.
- Retired PageIds stay occupied.

## Remaining must-fix

None. I tried to build blocker scenarios and none survived checking against the files:

- **Publish vs. block/reject race:** serialized, and blocked work cannot be published.
- **Wedged slots during a model outage:** the deadline produces blocked, and the sweep clears it.
- **Worker frees slots:** `Knowledge` has no `decide`, and G3 tests the denial.
- **Curator approves its own work:** denied at the server.
- **Reject replay under a new key:** only an identical result is returned; contradictory decisions fail.
- **Key injected through the journal:** rejected by the type system.

## Should-fix (non-blocking)

1. **Heading normalization in `verify.py`.** It matches `line.startswith("## Verdict:")` exactly. A contradictory heading indented by 1–3 spaces, or written at another level (e.g. `### Verdict: …`), would not be counted, and Markdown still renders such lines as headings. Normalize leading whitespace and any `#{1,6}` level, then add a test. In-scope cases already fail closed, and reports are written under a format constraint.
2. **Pagination in the usage example.** The architecture example processes only the first `pendingProposals` page. Show the cursor loop to the scan cutoff, because the prose requires completing the bounded scan.
3. **Outages become terminal rejections.** Under the default policy, a review-model outage turns every in-flight proposal into a terminal rejection. No text is lost (records persist, and the proposer sees the outcome via `operation`). Still, consider documenting a proposer re-submission path, or distinguishing infrastructure `review-timeout` in operator alerts.
4. **Error code for journal call-ID reuse.** Name the `KnowledgeErrorCode` for reusing a journal call ID with a changed payload (presumably `key-reuse` or `invalid-input`).

## Checks performed

- Read all nine required files end to end. Did not read RATIONALE.md, provenance.json, VERIFICATION.md, the receipts or any `.cache` logs.
- Traced M1 through step 1, step 4, step 7, the state table, "Curator actor and discovery", "Retrieval and evidence", and DELIVERY G0, G1 and G3.
- Counted the 12 `@ts-expect-error` controls in `contract.test.ts` and checked by reasoning that each targets a real type distinction:
  - brand mismatch `Digest`/`ReviewDigest`
  - `key?: never`
  - `Pick` omitting `propose`
  - missing `base`/`diff`
  - `private-evidence` excluded from `Passage`
  - retired `allow-degraded` literal
  - barrier and key-disclosure cases
- Checked by hand the architecture example against the declarations:
  - `prepare` overload selection
  - narrowing of `item.state` to blocked so `.reason` is typed
  - `reason` union assignable to `string`
  - `reviewDigest` typed as `ReviewDigest`

  It appears consistent.
- Counted 17 checker tests and read the `latest_review_status` logic for fail-closed paths and the positive path.

## Checks not performed

- I executed nothing: no tsc, no unittest, no CLI fixtures. The `validation.json` exits, hashes and counts are the operator's record, which I did not independently reproduce.
- I did not verify the input hashes in `validation.json` against the current bytes.
- The CLI fixtures are synthetic receipts, and all four failing-case commands share one path and output hash. I cannot tell the variants apart from the record alone.
- No SQLite, CAS, journal recovery, backlog fill/reject/restart, restore, QMD, MCP, OS-identity or host-child behavior has been exercised by anyone. These remain mandatory gates G0–G8.
