# Design for closing G2

Status: proposed against `c25ea64`. This is an implementation sketch. The measurements below describe the existing code.

## Problem

G2 requires accurate retrieval, supported answers, and bounded recall under the same frozen release profile. The latest candidate recovered 95.1% of held-out evidence overall. Multi-page completeness was 26 of 30 and paraphrase recall was 85%, below the 90% floors. Clause search improved development multi-page completeness from 95% to 100% and recovered no additional required pages on the holdout. Under ten readers, warm recall p95 was 10.10 s against 8 s. Publication visibility already passed at 18.81 s against 30 s. The answer model answered 9 of 30 controls, and 28 of its 408 quotes were absent from the nominated passages. Independent semantic review remains pending. [Phase P run](../../.verification/phase-p/20261118T191849.json) · [Frozen criteria](DECISIONS.md#d2-evaluation-corpus-hybrid-human-labeled-thresholds-frozen-now)

The next retrieval change depends on whether the required evidence entered the candidate set, survived ranking, and fit in the final response. The point of loss for each remaining miss is still unknown. The latency measurements show both vector queue delay and reranker scoring in slow calls. The effect of a proposed scheduling change still needs measurement.

## Usage

An MCP caller continues to send `wiki_recall`. `require-hybrid-current` keeps its freshness requirement. `best-available` may return a context with its actual coverage and degradation. Both retain exact, project-scoped citations.

```ts
const result = await recall(binding, {
  query,
  coverage: "require-hybrid-current",
  maxBytes: 24_000,
})
```

The answer runner passes the returned evidence and the question to a local answer adapter. The adapter returns the committed answer format for scoring. The evaluator separately retains the raw model draft and the adapter's verdict in the private run directory.

```python
outcome = answer_local(question, evidence_packet, frozen_profile)
scored = score_answers(questions, split, rankings, answers, reviews, thresholds)
```

The operator still uses the recall, answer, and performance commands documented for v2. A development diagnostic reports which stages can recover the required evidence. The release checker reads receipts from the frozen candidate. [Eval commands](EVAL-V2.md)

## Shape

### Trace required evidence before choosing the retrieval change

- Extend `trace_v2` to follow required pages and, when the frozen label has one, the exact gold span. Record membership after lexical and vector search, clause contributions, rerank admission, final ranking, and byte packing. Mark page-only labels as span-unscorable. Preserve the official page-level metric.
- Compute two optimistic ceilings locally on development. The first asks whether the authorized candidate union contains every required page. The second finds the largest set of required facts that can fit using complete, authorized passages. Use the real JSON encoder with citation metadata, the ten-passage cap, and the overlap rule. Mark an unresolved feasibility calculation as unknown. Report ceilings separately from measured recall.
- If the candidate ceiling is low, compare a bounded candidate-generation change against the baseline. If the candidate ceiling is high and selection loses facts, compare a bounded selection change that reserves evidence for distinct question parts. Keep exact identifiers, current revision filtering, and exact authority resolution. Pick one challenger from evidence and run the full development split, including controls and safety checks. Keep held-out item data out of tuning.

### Limit native work within the current recall implementation

```ts
type SearchPlan = Readonly<{
  primary: string
  supplemental: readonly string[]
  deadlineMs: number
}>

type SearchResult =
  | { kind: "complete"; primary: readonly VectorHit[]; supplemental: readonly (readonly VectorHit[])[] }
  | {
      kind: "supplemental-incomplete"
      primary: readonly VectorHit[]
      completed: ReadonlyMap<number, readonly VectorHit[]>
      reason: "deadline" | "reader-error"
    }
  | { kind: "primary-unavailable"; reason: "deadline" | "overloaded" | "reader-error" }

interface GenerationReader {
  search(plan: SearchPlan): Promise<SearchResult>
}
```

`qmd-integration.ts` owns admission, the generation lease, and native work lifetime. Keep one warm native reader as the initial resource budget. Serve accepted primary searches in arrival order. Use at most one native search per dispatch so a supplemental group cannot block all later primaries. Freeze queue limits after measuring memory and load, with enough admission capacity for the ten-reader workload. Remove expired queued work at its absolute monotonic deadline. Running native work keeps its slot and lease until it settles. The caller's completed result remains final if native work returns after expiry.

A strict request with unavailable current primary vector evidence returns `not-ready`. `best-available` can use the existing fallback with explicit coverage and degradation. When only supplemental work is incomplete, record which clause indexes completed and emit degradation through the existing result path. Freshness describes the generation used. The report records incomplete work and reranker admission separately from freshness.

Use an identical development workload to separate queue wait, model and generation verification, reader setup, search, snapshot, ranking, and final resolution. Move preparation out of the native queue only when integrity checks remain valid at point of use and closed generations cannot be accessed. Retain pinned model checks, one active GPU rerank, and exact result verification. Measure the quality of the contexts that callers actually receive under contention. Count every scheduled request and record refusals, fallback, and rerank admission in the observations.

### Admit answers against the exact evidence packet

```ts
type EvidenceRef = Readonly<{ passage: number; firstLine: number; lastLine: number }>
type NonEmpty<T> = readonly [T, ...T[]]
type AbstentionReason = "missing" | "conflict" | "degraded"
type EvidencePacket = Readonly<{
  coverage: "hybrid-current" | "hybrid-stale" | "lexical-only"
  passages: readonly Passage[]
}>
type AnswerDraft =
  | { kind: "answer"; claims: NonEmpty<{ text: string; evidence: NonEmpty<EvidenceRef> }> }
  | { kind: "abstain"; reason: AbstentionReason }

type AnswerOutcome =
  | { kind: "answer"; claims: NonEmpty<{ text: string; evidence: NonEmpty<Passage> }> }
  | { kind: "abstain"; reason: AbstentionReason }
  | { kind: "invalid-draft"; reason: "malformed" | "unresolved-reference" }

declare function admitAnswer(draft: AnswerDraft, packet: EvidencePacket): AnswerOutcome
```

The local answer adapter owns model reply validation, evidence admission, and the final answer. Passage references are scoped to the packet and use complete LF lines. The adapter resolves valid references to the exact text and authority citation. Invalid references or malformed replies keep a distinct failure outcome. A valid reference establishes byte identity. Independent review still establishes whether the cited lines support the claim and whether the answer is complete.

The sketch uses the existing `Passage` contract. Passage numbers and line bounds are one-based, with both line bounds inclusive. Split on LF and preserve the exact returned text. The adapter rejects out-of-bounds or reversed ranges and translates valid ranges by the parent citation's starting line. It retains the parent revision and full-body hash. Render the existing answer format at the runner boundary when an answer is admitted. Invalid drafts stay in the scored denominator as failures.

First compare the current answer profile on retrieved context and on an authorized evidence-only context for development positives. Keep the paired controls independently labeled. Use this comparison to see which failures survive when evidence is available. The candidate asks for support for each required fact and chooses the existing missing, conflict, or degraded outcome when the evidence is insufficient. Try a separate local sufficiency check only if the paired experiment shows the draft policy still misses the control limit. Measure false abstentions on answerable items alongside the control improvement.

`answer_v2.py` should call this adapter and score the emitted outcome. It keeps the raw draft for review. Replay and review attest to the ordered packet and answer under the frozen profile. Any earlier malformed output or unsupported control stays in historical results. A completed run with an independently decisive structural failure can receive a `FAIL` receipt with semantic review marked pending. A pass requires completed independent review. Partial runs retain their checkpoint status.

## Synthesis decision

Use the authority-preserving, in-process design. The independent judge selected it for the same reason. It keeps one public recall operation and puts scheduling behind the generation lease. The local answer adapter owns evidence admission behind one call. Both can be measured separately against the current candidate. The design takes generation-scoped lifetime checks and full resource accounting from the separate-service option.

The separate-service option gives the native worker ownership of a verified generation catalog and a bounded search queue across callers. It adds a process protocol, restart and lease coordination, and reader handoff during promotion. Existing peak reader RSS leaves about 66 MiB below the gate limit. Measure total service memory during promotion before considering additional resident contexts. Keep this option available if the in-process experiment shows that one native reader cannot meet the same quality and latency targets.

The in-process option accepts one native reader as an initial limit while preserving the known memory profile. Interleaving work can reduce head-of-line blocking. The baseline comparison must show whether the measured service time still needs to fall. The answer policy accepts conservative abstention while the paired replay quantifies the effect on answerable questions.

## Proof in order

1. **Establish the baseline.** On development, produce per-stage loss counts, the two evidence ceilings, paired answer outcomes, and same-request latency breakdowns. Use those observations to select the retrieval challenger and the smallest native scheduling change worth testing.
2. **Verify each change at its boundary.** Drive the public generation lifecycle with synthetic fixtures. Exercise timeout, promotion and restore while a reader holds a lease. Hash the actual generation files before and after native reads and test corrupted model and generation inputs. Exercise citation identity and byte caps, invalid evidence references, conflicting evidence, and incomplete model replies. Use the full development split to check that control improvements preserve positive-answer quality.
3. **Freeze and measure one candidate.** Bind commit, corpus hashes, model hashes, prompt, retrieval settings, scheduling and degradation policy, and runtime. Keep the previous failed runs. Run the fixed held-out and ten-reader overlapping-publication workloads on the same candidate. Record reader RSS and peak simultaneous service memory during promotion, including any processes added by the design. For a changed profile, use independently frozen evidence under the post-measurement rule. Keep private material local. [Evaluation confidentiality](EVAL-V2.md#confidentiality) · [Post-measurement rule](DELIVERY.md#gate-g2-recall-and-answers)
4. **Prove the gate.** Write current clean-identity receipts for retrieval, performance, and reviewed answers. Refresh the hybrid runtime, retrieval lifecycle, context cap, and measurement checks for the same commit. Inspect every G2 row in `check_gates.py --json`. Passing means each G2 row reports `PASS`, including measured recall, abstention, exact citations, byte cap, RSS, and visibility. Phase H follows the existing approval and host order.

Implementation and live validation require a new Phase P budget. The first implementation unit is the development-stage diagnostic and paired replay. Its result determines whether the next change belongs in candidate generation, selection, or the answer adapter.
