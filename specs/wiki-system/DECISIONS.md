# Owner decisions

Decisions the project owner made about scope, budget, data and access. Each entry is dated. A later entry may supersede an earlier one; entries are never edited after the fact. DELIVERY.md's acceptance rules still apply: no decision here turns a failed or skipped gate into a pass.

## 2026-11-15: completion approach

The owner approved the recommended options in [COMPLETION-PLAN.md](COMPLETION-PLAN.md) section 5.

### D1. Execution budget: per phase

The execution STOP in `src/p8/RELEASING.md` is lifted only phase by phase. Each phase gets DELIVERY.md's execution limits. A phase that exhausts its limit stops, with the blocker recorded in a receipt. A phase that needs host or provider runs starts only after the owner approves that phase.

| Phase | Approved | Limit (DELIVERY.md) |
|---|---|---|
| E: evaluation set v2 (G0) | yes | two working days, one ambiguity-review pass |
| P: G2 retrieval and answers on the local approved endpoint only | yes | three build/test iterations, at most five working days |
| H: hosts (Pi, Codex CLI, Claude Code, OpenCode) | not yet; needs approval at phase start | two repair/retest cycles and two working days per host |
| S: production isolation | deferred (D4) | — |
| R: independent G8 | not yet | one review, one correction cycle, one rerun |

### D2. Evaluation corpus: hybrid, human-labeled, thresholds frozen now

- **Content.** Real project knowledge forms the base. Synthetic additions fill categories the real material lacks, such as cross-project lookalikes, superseded decisions and child-written facts. Exactly which real sources are permitted is recorded in a separate entry. Corpus text goes only to the approved local endpoint (`local-llamacpp`, `qwen3.8-35b-a3b-mtp-32k`, thinking off).
- **Labels.** A human labels ambiguous items. Model-only labeling does not count as the independent reviewer.
- **Thresholds.** DELIVERY.md's proposed G2 thresholds are confirmed unchanged and frozen before any v2 measurement:

| Measurement | Frozen gate |
|---|---|
| Evidence recall@10, macro across positive questions | ≥ 95% |
| All-required-evidence@10 for multi-page questions | ≥ 90% |
| Hard paraphrase and cross-language slice recall@10 | ≥ 90% each |
| Agent answers correct and supported, answerable holdout | ≥ 90% |
| Exact citation revision/hash/span resolution | 100% |
| Unsupported confident answers on negative/conflict controls | ≤ 5% |
| Cross-project disclosures; superseded facts presented as current | 0 |
| Returned context size | ≤ frozen UTF-8 JSON byte cap (24,000 default) |
| Warm recall p95 (≥100 timed queries, ten readers, overlapping writes) | ≤ 2 s (raised to ≤ 8 s by D11) |
| Committed-to-hybrid visibility p95 | ≤ 30 s |
| Service peak RSS | ≤ 2 GiB |

Any revision after measurement is post-hoc under DELIVERY.md: the failed result stays, and the owner approves a new frozen profile and a rerun.

### D3. Host access: per-run test profiles, OpenCode retried first

- **Codex CLI and Claude Code** run with per-invocation profiles that allow only the project wiki MCP tools, listed in [HOST-TEST-PROFILES.md](HOST-TEST-PROFILES.md). No global or user configuration changes. The owner reviews that file before the first run.
- **OpenCode.** 1.19.5 is installed, the latest published version. Its `build` agent permits the `task` tool, and a `general` subagent exists, so the earlier "no native child launcher" result is treated as a configuration problem to retest, not a missing feature. A release-scope change is considered only if a test-profile run shows that native children are really unavailable.

### D4. Production isolation: deferred

Separate OS identities and an off-disk backup target are deferred until correctness and hosts are verified. Until then, any release would be scoped to single-user trusted local use, with G3 isolation recorded as not established. `g3.production-os-identities` stays MISSING.

## 2026-11-15: corpus sources and labeling (D5)

- **Real source:** Pi LLM Wiki pages only (`~/.pi/agent/llm-wiki/wiki`, 2,009 pages). Orthotrack and repo docs are not approved. Synthetic material fills the remaining categories.
- **Confidentiality:** page text and anything derived from it (questions, answers, labels, model outputs) goes only to the local approved endpoint. It never goes to Claude, Codex, other providers, claude.ai Artifacts or Git. Corpus data lives in ignored `.cache/eval/v2/`; Git holds only the manifest with hashes. Claude sessions inspect it only through aggregate, content-free scripts.
- **Labeling:** the owner labels ambiguous items in a local HTML page opened from disk. It is not a published Artifact, because that would send text to claude.ai.

## 2026-11-15: assisted labeling (D6)

- **Request and options.** Labeling all ambiguous items by hand was too much work. The owner asked about Codex (sol-6.1), was told that it would send wiki text to its provider in breach of D5, and chose **assisted local labeling** instead. D5 is unchanged.
- **How it works.**
  - `build_v2.py suggest` runs the local endpoint as a skeptical judge over every item that needs a label.
  - The judge sees evidence the generator never saw: the five most related other wiki pages, ranked by IDF-weighted word overlap with no model involved. For missing-answer controls, it must look for an answer in them.
  - The labeling page shows the suggestions, lowest confidence first. It offers one-click confirmation and a bulk confirm for confidence ≥ 0.8.
- **Provenance.** Each label records `source` as `owner` or `suggestion-confirmed`. The manifest records the counts by source and the judge prompt hashes.
- **Known weakness.** The judge is the same local model as the generator, so confirmed suggestions are weaker evidence than independent human labels. Reports state the split, and items the owner decided directly are not mixed up with confirmed suggestions.

## 2026-11-15: Codex as labeling judge (D7), an exception to D5

- **Decision.** Shown that Codex's configured model (gpt-6.1-sol, no custom provider) runs on OpenAI's cloud, the owner chose to have Codex judge **all** items that need labels. This is a narrow, owner-approved exception to D5. Everything else in D5 stands: no wiki text goes to Claude, claude.ai Artifacts, Git or any other provider.
- **What goes to Codex and how.**
  - Content: for each item needing a label, the question plus clipped text of the shown and related pages. This is the same evidence the local judge gets.
  - Command: `build_v2.py codex-judge` sends it directly to `codex exec` with `--ignore-user-config --ignore-rules --ephemeral -s read-only`, an empty working directory and a strict output schema. Codex gets no MCP servers and no repository access.
  - Logging: responses are cached under `.cache/eval/v2/`, and nothing is printed.
- **Verification is unchanged.** Evidence checks are done by code, the same as for the local judge. A "the answer is in the wiki" claim counts only if its quote is found verbatim, and extra gold pages must be among the candidates shown.
- **Provenance.** Each confirmed label records its `judge`, and the manifest counts labels by source and by judge. Codex judgments are not deterministic, so the cached responses are the record. The run also reports how often Codex agrees with the local judge.

## 2026-11-15: Claude Fable 5.2 as labeling judge (D8), an exception to D5

- **Decision.** After the Codex run, the owner asked for Claude Fable 5.2 (`claude-fable-5-2`) to do the judging. This is a narrow, owner-approved exception to D5's "never to Claude" rule. It covers only the judge calls described below. The interactive Claude Code session still never reads wiki text, and nothing goes to Artifacts or Git.
- **How it is called.**
  - Command: `build_v2.py fable-judge` sends the same evidence as the other judges to `claude -p --model claude-fable-5-2`, using the owner's existing login.
  - Isolation: no tools (`--tools ""`), no MCP servers (`--strict-mcp-config`), no settings (`--setting-sources ""`), no session persistence, an empty working directory and a strict JSON schema.
  - Logging: responses and per-call cost are cached under `.cache/eval/v2/`, and nothing is printed.
- **Verification and provenance** follow D7: evidence is checked by code, and each confirmed label records its judge. Agreement with the local and Codex judges is reported, and the Codex run's results are kept for comparison.

## 2026-11-17: labeling delegated to the judge (D9)

The owner asked that Fable settle the remaining labels instead of downloading them from the browser page. `build_v2.py delegate-labels` writes each item's current suggestion into `labels.json` with `source: "delegated"`, the judge's name and whether code verified its evidence. It never overwrites a label the owner set, and it leaves items with no verdict unlabeled. The final suggestions come from Fable 5.2, using its second pass where one ran. The manifest counts delegated labels separately from owner and owner-confirmed labels, so reports can show that the eval set's controls and ambiguous items were labeled by a model under owner delegation, not by a human.

## 2026-11-17: Claude Opus 5.5 judges the refill items (D10)

Fable 5.2 ran out of usage credits before it could judge the 15 refill items (14 missing-answer controls and 1 conflict control). The owner chose Claude Opus 5.5 (`claude-opus-5-5`) at high effort for those items. The command is `build_v2.py opus-judge`. It uses the same evidence, isolation and code checks as D8, and the D5 exception from D8 extends to this model. Only unlabeled items are judged, so the earlier labels keep Fable as their judge. The manifest counts labels by judge.

## 2026-11-17: eval data fix, reranker by default, recall latency budget raised to 8 s (D11)

- **Eval data fix.** The first held-out run (k = 10) counted 1 superseded fact shown as current. The item's old text was a 10-character phrase that also appears in 22 current pages, so the check could not tell a stale fact from a common phrase. A superseded span must now be absent from every current page, not only from the edited one (`item_still_valid`, `current_bodies`, and a generation-time `old-text-elsewhere` rejection). Revalidate dropped exactly 2 held-out items. They were refilled on the local model and the set was re-frozen with the stable split.
- **Held-out result before any change below (k = 10, re-frozen set, recorded as FAIL):**
  - Failing: recall@10 0.929, multi-page all-evidence 0.767, paraphrase 0.817.
  - Passing: Ukrainian 1.00, superseded-as-current 0, cross-project disclosures 0, citations 100 %, serial p95 0.55 s.
  - Under D2 this failed result stays on record.
- **Reranker.** A cross-encoder reorders the fused top 30 chunks (full text, up to 512 tokens each) before passage selection.
  - Model: Qwen3-Reranker-0.6B Q8_0 (`hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`), SHA-256 `22c9979c…a48`, checked when it loads.
  - Runtime: its own llama.cpp ranking context on Vulkan. The embedding model and the index stay on the CPU path.
  - Configuration: `WIKI_RERANK_MODEL`; reranking is off when it is unset.
  - Development half, 156 questions: recall 0.915 → 0.949, multi-page 0.80 → 0.90, paraphrase 0.85 → 0.95, serial p95 0.56 s → 7.6 s.
  - Rejected variants: depth 15 or 128-token heads, and a query-focused 96/160-token window. Both lost the recall gain and still took 2.7–4.4 s. A fixed overhead of about 50 ms per candidate dominates, and parallel contexts did not help on the Radeon 780M iGPU.
- **Budget.** The owner raised the warm recall p95 budget from 2 s to 8 s.
  - The GPU serves one ranking at a time. A query that finds the reranker busy keeps the fused order (`degradation: "reranker-busy"`) instead of queueing, so the ten-reader p95 stays bounded.
  - Under load, recall for those queries is the fused-order recall.
  - The frozen manifest's `warm_recall_p95_seconds` is now 8.0. Every other D2 threshold is unchanged.
- **Held-out result with the reranker** (depth 30, 512 tokens, Vulkan; one run, recorded as FAIL). Run `20261117T211912`.
  - Failing: recall@10 0.941 (CI 0.90–0.97), multi-page all-evidence 0.867, paraphrase 0.85.
  - Passing: Ukrainian 1.00, superseded-as-current 0, disclosures 0, citations 100 %, max context 23,990 bytes, serial p95 7.05 s.
  - The ten-reader p95 under the 8 s budget is not yet measured.
- **Ten-reader latency** (`src/eval/perf_readers.ts`): synthetic v1 corpus, 10 readers × 10 queries, one overlapping write.

  | Setup | p95 | Warm p95 | Reranked | Slowest reranked query |
  |---|---|---|---|---|
  | Reranker off, one shared process | 2.65 s | 2.04 s | — | — |
  | Reranker on, one shared process | 4.37 s | 4.37 s | 6 of 100 | 12.9 s |
  | Reranker on, ten processes | 3.23 s | 2.84 s | 10 of 100 | 9.8 s |

  - The 8 s budget is met in every setup.
  - Under ten concurrent readers, about 90 % of queries are not reranked (`reranker-busy`). Their recall is the fused-order recall, not the reranked one.
  - A single reranked query can exceed 8 s under load, because it competes with the other readers' CPU embedding.

## 2026-11-18: exact-identifier route and protected fused top 2 (D12)

- **Diagnosis.** The development trace (`trace_v2`) reproduced recall 0.9485 and located all 8 missing gold pages:
  - 6 were found by neither branch: 4 lookalike, 1 identifier, 1 paraphrase.
  - 1 was outside the reranker head.
  - 1 was demoted by the reranker from fused rank 2 to rank 14.
  - No returned page contained the missing gold spans.
- **Change.** Both rules were chosen from a grid frozen before the offline replay of the trace.
  - **Exact identifiers.** `snapshot` returns the chunks that contain an identifier-shaped query token verbatim. The token must be at least 4 characters, case-sensitive, word-bounded and found in exactly one object of the project. Those chunks go first.
  - **Protected fused top 2.** After reranking, the first chunk of each of the fused top 2 objects stays in front.
- **Replay variants that were rejected.**
  - Weighted RRF blends of the reranker and fused orders lost a superseded item.
  - Reserving 3–8 reranker-head slots for vector-only chunks gained nothing and lost gold pages.
- **Result on development, measured** (run `20261117T233046`). Every check passes:
  - recall@10 0.9485 → 0.9596;
  - multi-page 0.90 → 0.95;
  - paraphrase 0.95;
  - identifier 0.94 → 1.00;
  - superseded-as-current 0, disclosures 0, citations 100 %;
  - serial p95 6.8 s.
  - The busy-fallback order, replayed, goes from 0.9265 to 0.9338.
- **Caveats.**
  - The identifier pattern resembles the eval builder's identifier definition, so the identifier gain may overstate real-world benefit.
  - The evidence is one recovered question per rule, on 156 questions.
  - The holdout was not used for these choices.

## 2026-11-18: ambiguous lookalike items judged (D13)

- **Defect.** The cross-project-lookalike generator never ran the ambiguity check that other slices use. 12 lookalike items (8 development, 4 holdout) had a gold span that also appears verbatim on another main-project page, yet were never flagged for labeling.
- **Fix.**
  - The generator now flags lookalike items whose span (at least 10 characters, the slice's own minimum span length) occurs on another main page.
  - `build_v2.py flag-ambiguous` flagged the 12 existing, unlabeled items. It never touches labeled items.
  - `label_context` uses the same 10-character threshold, so the judge sees every page that contains the span.
- **Judging.** The owner chose judge labeling. Claude Opus 5.5 judged the items under the D8/D10 isolation and code evidence checks.
  - First pass: 10 rejected, 2 accepted, 0 unverified.
  - The refill on the local model produced 2 more ambiguous items, and both were rejected.
- **Effect on the set.** 7 development and 3 held-out items were replaced. No item moved between splits. The set was re-frozen at 390 questions, 234 held out.
- **Development result on the corrected set** (run `20261118T004310`, D12 retrieval):
  - recall@10 0.9706;
  - multi-page 0.90 (exactly at the threshold), paraphrase 0.95, lookalike 0.90;
  - superseded-as-current 0, disclosures 0, citations 100 %.
  - **Serial p95 was 8.002 s, just over the 8 s D11 budget.** The latency work is now required, not optional.

## 2026-11-18: reranker depth 24, deterministic retrieval, title-aware embeddings (D14)

- **Latency.**
  - On the corrected set (D13), development serial p95 was 8.002 s at reranker depth 30, just over the 8 s budget. Depth 24 (512 tokens) brought p95 to about 6.2 s, and every development check still passes.
  - A persistent kernel-`flock` helper per process replaces the two `python3` spawns per query for the generation lock.
- **Eval noise found and removed.** Two development runs with identical settings differed on 56 of 156 questions. Earlier single-question comparisons, including depth 24 against 30, were therefore within noise. The cause was revision-derived chunk keys, which change each time the same content is loaded:
  1. Fusion ties and bm25 ties were broken by key. They are now broken by best branch rank, then lexical rank (fusion), and by kind, object and start (bm25), before the key.
  2. **A production defect:** QMD embeds `title: <first heading or file name> | text: ...`. Chunk files were named by key, so headless chunks (189 of 2,352) were embedded with a random 64-hex title. This produced noisy vectors that changed on every rebuild: 376 vectors differed between builds, cosine as low as 0.675.
     - Every chunk file now starts with `# <page title>`, which also adds page titles to all embeddings.
     - Citations never come from QMD text.
- **Result.** Two development runs (`20261118T040716`, `20261118T043034`) returned identical passage lists for 156/156 questions.
  - recall@10 0.9669, multi-page 0.95, paraphrase 0.95, Ukrainian 1.00;
  - superseded-as-current 0, disclosures 0, citations 100 %;
  - serial p95 6.2 s.
- **Typing.** The eval TypeScript tools are now part of the strict Tier A type check.
