---
type: plan
context: wiki-comparison
---

# Wiki comparison

## Scope and prior art

Compare existing tools before writing a replacement wiki. The required behavior is durable cited knowledge, high retrieval recall, access from independent Pi sessions and child agents, and explicit handling of simultaneous writes.

Candidates:

- `@zosmaai/pi-llm-wiki`: installed Pi-native capture, recall, metadata and background-agent implementation. Test the actual exported functions and the actual Pi extension, not a reimplementation.
- `nvk/llm-wiki`: pinned Git checkout. Its query-lite profile is an agent workflow, not a ranking algorithm. Test it through Pi against the same corpus; do not assign it fabricated standalone retrieval scores.
- `@tobilu/qmd`: installed local search engine. Test BM25, vector search and explicit lexical/vector fusion separately. The announced embedding experiment downloaded one 334 MB model into ignored storage. No expansion model or reranker was downloaded.
- SQLite FTS5 BM25: a transparent model-free control, not a proposed production wiki.
- MCP Memory Service: added after the user clarified that QMD is optional. Review its pinned source, license, shared API and database writes. Do not claim a retrieval or concurrency score without running it.
- The Swarm template, metadata filtering, structured hierarchical retrieval, redmizt, Stash and Newsroom: compare their actual roles, requirements and licenses in the source report. They are not interchangeable search backends.

## Experiments

1. Freeze a small synthetic corpus and gold page IDs before running retrieval. Include identifiers present only in bodies, paraphrases, Ukrainian text, cross-document questions, a superseded decision and negative controls. Keep answers and gold IDs out of all search indexes and agent workspaces. A separate four-query exploratory challenge was added after the first pilot, without changing documents or engine settings.
2. Measure recall@5, all-required-pages@5, reciprocal rank, negative-query false positives and per-query elapsed time. Keep raw ranked results. Do not equate search scores across engines.
3. Run independent read-only Pi sessions for each agent-capable candidate on matched questions with the same local model and declared tools. Record actual tool calls, citations and output. Separate search quality from agent query planning.
4. Save a synthetic insight in session A and retrieve it from a fresh session B. Exercise an actual child-agent runner with explicitly supplied wiki tools. This does not automatically prove compatibility with every third-party subagent extension.
5. Run independent writer processes, then check files, events, registry validity and visibility after reconciliation. Test both distinct-page writes and same-page collisions. Finite successful stress runs are evidence, not a proof of concurrency safety.
6. Publish the measured results and a reuse/extend recommendation. Leave production configuration unchanged.

## Isolation

All upstream checkouts, generated vaults, databases, private runtime configuration and raw Pi transcripts live under ignored `.cache/`. Version-controlled evidence contains only synthetic data, metrics, relevant tool outcomes and source provenance. No real personal vault is read or modified. No LAN service is changed. Model calls use the existing local endpoint.

The previous root commit contains a LAN password. The local file is kept but untracked. Do not publish this repository's history until the password is rotated and history is sanitized through a separately approved operation.

## Recorded outcome

All six experiments have saved evidence. See [the comparison report](README.md). The session and child tests passed, but harder lexical queries and concurrent source capture failed. QMD vector retrieval found the harder pages and also returned irrelevant results for the two negative controls. No production adapter or writer queue was implemented.

## Limits

This is a small diagnostic benchmark, not a production recall guarantee. Manual gold judgments and one local model cannot settle performance on a large real corpus. Report unavailable modes and failed runs rather than substituting guessed results.
