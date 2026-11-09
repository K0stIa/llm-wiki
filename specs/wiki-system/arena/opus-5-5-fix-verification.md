## Verdict: NEEDS-REVISION

This is a design-level verdict only. It does not certify production readiness, and runtime gates G0–G8 have not been run. Items 1–8 and all of item 9 now have coherent fixes in the current files. One gap remains, created by the item 2 fix: a blocked proposal has no way out, but it still counts against the admission cap. The fix is a few sentences.

## Resolution table

| Item | Status | Evidence (file / heading) |
|---|---|---|
| **1. Full-page read / silent drop on replace** | **Resolved** | `contract.d.ts`: `Knowledge.page` returns `PageSnapshot` (the whole body plus its hash). `Review.replace` and `Review.retire` require `base: PageSnapshot` and `diff`. `ReviewDigest` is a separate type from `Digest`, and `DecisionInput.reviewedDigest` attests to it. ARCHITECTURE "Proposal and publication state machine" step 4: the digest covers the full base, the proposed body, the diff, the sources and the epoch. Bundles too large to review become blocked, never partly reviewed. DELIVERY G1 includes a case where a partial replacement must show every removed line. `tests/contract.test.ts` has a negative test, `partialReview`, and a `wrongReviewDigest` test. |
| **2. Curator actor, discovery, credentials, inheritance, injection, latency** | **Mostly resolved; one new gap (see must-fix)** | ARCHITECTURE "Curator actor and discovery": one dedicated reviewer process that cannot spawn children, delegate, run a shell or read arbitrary files. It runs as a separate OS identity, and its credential is a 0600 file outside paths workers can read, never in prompts or worker environment/MCP configs. `pendingProposals` uses a keyset cursor (default 20, max 100). The design also sets a full-rescan rule, an immediate durable wake-up, a 150 s deadline with one infrastructure retry, and a backlog cap of 100. Proposers see their own proposals through `OperationState.proposal-accepted.snapshot`. G3 covers curator-targeted injection, worker access to curator files and denial of curator child creation. G4 step 1 requires a reviewed terminal decision within 150 s. |
| **3. Epoch, sequence, retained vs lost IDs across restore** | **Resolved** | The contract defines `ProjectRevision = {project, epoch, sequence}`, plus a `stale-epoch` error. ARCHITECTURE "Restore identity and exact reads": every restore gets a fresh unpredictable epoch. Old index targets and review attestations become invalid. Restored pending proposals need a new review. IDs are creation epoch plus a random UUID. Lost IDs return not-found, and old mutations are not replayed automatically. Retrieval step 2 discards any generation with a different epoch. G3 tests restoring to the same numeric sequence on a different history, and checks retained vs lost IDs. |
| **4. Token budget** | **Resolved** | The recall response cap is 24,000 bytes of compact `RecallResult` JSON, metadata included. `maxBytes` can lower it, down to a minimum of 2,048. If nothing fits, the result is `capacity`, not no-matches. Hosts budget model tokens separately. Sources: ARCHITECTURE "Retrieval and evidence" and DELIVERY G2 (the byte gate with UTF-8, emoji and escaping cases). |
| **5. Retry identity and shared principals** | **Resolved at design level** | ARCHITECTURE "Retry ownership and private proposals": before sending, the trusted adapter durably records the host call ID, key, request bytes/digest, project and principal. Model-facing schemas omit `key`. If the reply is lost before any receipt arrives, the adapter replays the same key and payload, and never mints a new key. A host that cannot persist this fails its mutation gate. The guarantee is stated honestly as at-most-once per persisted intent, not semantic deduplication. `CuratorProposal.duplicates` flags matching payloads. Children share the worker principal, and no per-child confidentiality is claimed. G1 crashes the adapter before send, after send, and after commit but before the receipt. OPUS_FIXES explicitly rules out server keys returned only after commit. |
| **6. Default vs strict freshness** | **Resolved** | `RecallInput.coverage` defaults to `best-available`, with labels `hybrid-current`, `hybrid-stale` or `lexical-only`. `require-hybrid-current` is opt-in and returns `not-ready`. The test fixture rejects the retired `allow-degraded` value. Degraded results never support an absence claim. |
| **7. Pending/rejected evidence visibility** | **Resolved** | ARCHITECTURE "Evidence visibility": captured text stays private and never enters FTS, QMD, recall or exports. Only the owner and the curator can read it. Recall returns only sources cited by an active published page. `ExactRead` has a distinct `private-evidence` variant, and the `leakedEvidence` negative test checks it. G3 uses a unique marker to check for leaks across principals. |
| **8. Budget, corpus and model-specific gates** | **Resolved** | DELIVERY "Execution limits": corpus construction has its own two-day line. The 12-day total overrides the per-unit ceilings and may end the rollout before OpenCode. Only the owner can extend it. G0 pins the answer profile (`qwen3.8-35b-a3b-mtp-32k`). G4–G7 step 6 reruns at least 30 answerable and 10 negative questions per host and model, and hosts do not inherit G2 scores. |
| **9a. Lexical simplification** | **Resolved; no new blocker** | Retrieval is now FTS5 (transactional, covering everything published) plus QMD vectors, with no tail scan or `incomplete` mode. The combination needs a fresh frozen benchmark. I checked how the new coverage labels and epoch rule interact, and found no conflict. |
| 9b. Conflict terminality | Resolved | State machine step 6. |
| 9c. Retired pages | Resolved | Step 3: a retired PageId stays occupied, so `create` cannot reuse it. |
| 9d. Citation hash scope | Resolved | The hash covers the whole stored body (Restore section and the contract comment). |
| 9e. Slice sizes | Resolved | G0 requires at least 30 held-out positives per hard slice, recorded overlaps and interval estimates. |
| 9f. Post-hoc profile changes | Resolved | G2: the original failure is kept, the owner must approve, and the gate reruns with a fresh frozen profile. |
| 9g. Host stop rule | Resolved | G4–G7: only the project owner can approve an alternative scope; otherwise the host stays blocked. |
| 9h. Pinned QMD generations | Resolved | "Index lifecycle": immutable generation directories, readers limited to search, and a G2 hash probe of generation files. It does not assume a read-only option QMD lacks. |

## Remaining must-fix

**M1: a blocked proposal has no exit and still counts toward the backlog cap, so admission can wedge permanently.**

- **Evidence**
  - ARCHITECTURE "Curator actor and discovery": the backlog counts every unresolved entry, pending or blocked, and excess submissions are rejected with capacity.
  - The curator "selects only pending entries for automatic review".
  - "No automatic loop retries blocked work without an approved change."
  - "Never drop already accepted work."
  - The design defines two transitions, pending → blocked and pending → decided. No document defines blocked → decided. The contract does not say whether `decide` on a blocked proposal is valid or raises `invalid-state`. No gate tests it.
- **Scenario**
  - The mutation cap is 262,144 bytes and page bodies may reach 32,768 bytes. The curator runs the same named 32k-context model.
  - A full replacement review needs the base, the proposed body, the diff and the sources. For large pages this can exceed that context. These proposals are accepted, then become `blocked: context-capacity`.
  - Reviews of large pages by a local 35B model under load can also hit the 150 s deadline and become `review-timeout`.
  - Once 100 blocked entries accumulate, every new proposal from every principal is rejected with `capacity`. Parent/child sharing stops for good, and no operation is defined to recover.
- **Smallest correction**
  1. State that `decide({kind:"reject"})` is valid on a blocked proposal, with its reason recorded. Allow it for the curator principal, or for an owner using `connectCurator`.
  2. Either exclude blocked entries from the admission cap, or set a separate cap for them.
  3. Reject at admission, with `capacity`, any proposal whose review bundle is larger than the frozen curator review budget. This matches the existing rule that "larger inputs fail capacity before acceptance".
  4. Add a G1/G3 case: fill the backlog with blocked entries, then show that a new proposal can still be admitted or that clearing them works.

## Should-fix (not blocking)

- **Identity wording conflict.** DELIVERY "Scope and defaults" says "Single trusted OS user". ARCHITECTURE requires the curator to run as a separate OS identity. That separation is what protects the curator credential from coding agents that have a shell, so DELIVERY should say so.
- **Journal has no type.** `hostJournal.prepare` appears only in the ARCHITECTURE usage example. A small `HostCallJournal` type, or prose under `hosts/`, would make the pre-send contract checkable. G1 already covers the behavior.
- **PageIds can be reused after a restore.** PageIds are chosen by the client, so a post-backup create that was lost leaves its PageId free to be created again. Exact citations are still protected because revisions are random IDs and citations carry a hash. The sentence "cannot be reallocated" should be limited to the server-generated IDs.
- **Curator could approve its own proposals.** `Curator extends Knowledge`, so the type allows the curator to call `propose`. The curator's toolset in the prose does not include it. State that the server rejects this, or that the curator may not decide on its own proposals.
- **FTS5 indexing granularity is unstated.** Say whether FTS5 indexes line-span chunks, so lexical hits produce citable spans that can be merged with QMD chunks.

## Checks actually performed

- Read every required file end to end: the original review, ARCHITECTURE.md, contract.d.ts, DELIVERY.md, OPUS_FIXES.md, `tests/contract.test.ts`, `verify.py`, `tests/test_verifier.py` and `validation.json`.
- Traced each original item and each focus area you listed (review digest binding, curator controls, epoch barriers, byte cap, pre-send journal, principals, freshness, visibility, budgets) against the prose and types.
- **Compiler tests.** The test file contains 7 `@ts-expect-error` cases, which matches the 7 recorded in `validation.json`. Each one targets a real type distinction.
- **Checker tests.** `test_verifier.py` contains 10 tests. In `verify.py`, any recorded verdict other than READY short-circuits to NEEDS-REVISION or UNREVIEWED. A READY needs the right provider, model and reasoning level, a matching report hash, a READY verdict line in the report, and current hashes for all three core files. Otherwise the result is STALE or UNVERIFIED.
  - Tests exist for: a newer failure overriding a READY, changed source, a tampered report, a READY receipt pointing at a failed report, path escape and malformed metadata.
  - By reading the source, I confirmed that an old READY cannot pass for changed source and cannot override a newer NEEDS-REVISION.

## Checks not performed

- I did not rerun any command. I could not verify the TypeScript 5.9.3 build, the 7 negative diagnostics, the 10 checker tests, the 14 research tests, or any hash in `validation.json` or `provenance.json`. I did not read `provenance.json`, VERIFICATION.md or RATIONALE.md.
- These checks cover the types and the checker only. None of them exercises service behavior: SQLite transactions, CAS, journal recovery, restore epochs, QMD generation pinning, byte caps, curator isolation or any host's children.
- No implementation exists. G0–G8 are unrun and are runtime gates, not completed work.
- I did not inspect QMD, MCP Memory Service or any host CLI source.
