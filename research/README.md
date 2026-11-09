# Wiki comparison results

Use this report to choose what to reuse. It replaces the previous prototype's unsupported capability claims. No replacement wiki is deployed.

## Recommendation

For a curated Markdown wiki, reuse existing Pi integration, add semantic retrieval and restrict writes to one curator. Do not rebuild the old scripts. QMD is the best-measured backend here, not a requirement.

The installed Pi LLM Wiki is a useful integration starting point. Its tested child runner and separate sessions can share persisted knowledge. Its default lexical recall misses harder paraphrases, and its source allocator loses data under concurrent capture.

QMD vector retrieval found those missing pages. This makes QMD the strongest tested retrieval candidate, not a complete wiki system. It still returns irrelevant pages for missing facts. The answering agent must check sources and abstain.

This combination remains a recommendation, not a completed application integration in this repository. Later architecture inspection confirmed that the installed Pi LLM Wiki already contains QMD adapters, journaled indexing/recovery and a standalone MCP server. Reuse those components before building equivalents. The required safe publication policy and verified deployment do not exist here.

[The subsequent production design](../specs/wiki-system/README.md) compares Markdown and database authority. It selects a transactional authority with derived exports and retrieval indexes. That design does not change the measured results below.

## Retrieval evidence

The corpus contains 24 invented documents. The initial suite contains 19 positive questions and two negative controls. A later, exploratory suite adds four harder questions. One asks in Ukrainian about an English document.

Recall@5 measures the fraction of required pages among the first five results. It does not measure answer correctness. Cross-document questions require every gold page to count as complete.

| Actual search mode | Initial recall@5 | Hard follow-up recall@5 | Negative controls returning results |
|---|---:|---:|---:|
| Pi LLM Wiki 0.12.5, lexical | 100% | 0% | 0/2 |
| QMD 2.8.3, raw BM25 query | 34.21% | 0% | 0/2 |
| SQLite FTS5, OR terms and English stemming | 100% | 50% | 0/2 |
| QMD vector search | 100% | 100% | 2/2 |
| QMD explicit lexical + vector fusion, no reranker | 100% | 100% | 2/2 |

The harder questions include "Where is yesterday's chat kept?" and "Де лежать попередні розмови?" Both refer to `concepts/session-records`. The easier suite alone hides lexical retrieval failures.

QMD's `searchLex` requires matching query terms together. Its low score on full natural-language questions is not a verdict on QMD's other modes. The SQLite control uses different tokenization and OR semantics.

The vector test uses QMD's default `embeddinggemma-300M-Q8_0.gguf`, a 333,590,944-byte download. It runs on CPU with an isolated cache. Encoding 24 document chunks took approximately 4.4 seconds after download. Initial-suite median query times were 15 ms for vector search and 18 ms for fusion. These are single-pass diagnostics, not load benchmarks.

No query-expansion model or reranker was downloaded. Fusion receives explicit `lex` and `vec` queries. It is not QMD's complete default expansion-and-reranking workflow. The GGUF model card does not declare a license. Check the original model terms before deployment. No weights are committed or redistributed.

Evidence:

- [Corpus and initial questions](fixture.json), [hard follow-up questions](challenge.json).
- [Initial raw rankings and provenance](results/retrieval.json), [computed metrics](results/summary.json).
- [Hard follow-up raw rankings](results/challenge-retrieval.json), [computed metrics](results/challenge-summary.json).

The follow-up questions were fixed after inspecting the initial pilot. They are exploratory, not an independent production test set. Neither engine settings nor document content changed for that follow-up.

## Actual Pi sessions and child agent

Both candidates used Pi 1.5.0 and the same `qwen3.8-35b-a3b-mtp-32k` model on the configured private-LAN inference server. Thinking was disabled. Each CLI invocation used a fresh session ID and isolated configuration. The host also offers a 256k model variant. This experiment used the 32k variant explicitly.

Pi LLM Wiki loaded its real extension. The nvk test loaded its pinned `query-lite` profile with read-only file tools. Both received equivalent synthetic documents and indexes. No gold answers or evaluation questions were placed in their workspaces.

| Check | Pi LLM Wiki | nvk query-lite |
|---|---|---|
| Browser closure question | Correct primary fact | Correct primary fact |
| Shared knowledge and child-tool configuration | Correct primary facts | Correct primary facts |
| Current provider after a superseded decision | Selected LocalVector | Selected LocalVector |
| Missing travel policy | Abstained | Abstained |
| Hard English paraphrase about stored chats | Incorrectly claimed evidence was missing | Found the session page |
| Ukrainian question about stored chats | Incorrectly claimed evidence was missing | Claimed the wiki directory was absent without checking |

These are manually checked outcomes from one run per question. They are not a full agent accuracy benchmark. Agents did not always follow the requested search sequence. A zero exit code means the session ended, not that the answer was correct.

The nvk Ukrainian failure is a false filesystem claim. Its `.wiki/` directory existed, and the agent made no tool calls. The Pi LLM Wiki Ukrainian answer also added an unsupported guess about a real storage path.

Persistence checks passed for Pi LLM Wiki:

1. Session A saved the invented marker `amber-orbit-592` through `wiki_retro`.
2. Fresh session B searched, read the saved source and recovered the marker.
3. The package's actual `runSubAgent` runner received explicit recall, read and retro tools. It read that source and saved `sources/child-probe` with the marker and provenance.
4. Another fresh Pi session read the child page and its original source.

The child had a new agent context. It did not inherit the parent's conversation. This tests the package's runner, not the separate `pi-subagents` extension or every worktree configuration. nvk query-lite deliberately has no save tool, so it received no invented write-support score.

Evidence: [CLI outcomes and tool calls](results/live.json), [actual child-runner outcome](results/child.json).

## Concurrent writes

The test uses eight independent Node processes calling installed Pi LLM Wiki functions against disposable vaults. It does not modify the installed package.

| Scenario | Acknowledged writes | Surviving contents |
|---|---:|---:|
| Distinct insight slugs | 64 | 64 |
| Same insight slug | 8 | 1 |
| Concurrent raw-source captures | 96 | 73 |
| Single-writer raw-source control | 96 | 96 |

All concurrent workers exited successfully. Events recorded all 96 captures, although only 73 distinct source packets survived. Rebuilding metadata could not restore overwritten source contents.

The allocator in `lib/utils.ts`, `nextSequentialId`, scans existing directories and returns the next number without reserving it. `lib/source-packet.ts` then creates that path with `recursive: true` and writes into it. Separate processes can choose the same ID and overwrite the same packet.

Same-page insight saves also use replacement rather than conflict detection or merging. A successful distinct-page test does not make arbitrary simultaneous writes safe.

The registry reader observed no malformed JSON during these runs. That proves neither a multi-file transaction nor conflict-safe editing. Serial capture avoided the demonstrated ID collision in the control.

The pinned nvk upstream session-concurrency regression passed all 11 checks. It exercised 96 live Stop-hook calls and a broken-writer control. This covers session-state JSON, not parallel edits to compiled wiki pages.

Evidence: [write counts, source hashes, reconciliation and upstream test results](results/concurrency.json).

## What the supplied projects contribute

Public-source provenance and licenses are recorded in [sources.json](results/sources.json). Installed package versions and source hashes are recorded with the retrieval results. No restricted upstream code was incorporated.

| Project | Checked role and requirements | Reuse decision |
|---|---|---|
| [Pi LLM Wiki](https://www.npmjs.com/package/@zosmaai/pi-llm-wiki), MIT | Pi tools, source capture, recall, metadata and its own child runner. Tested installed version 0.12.5. | Reuse integration, subject to serialized writes or upstream collision fixes. Add semantic retrieval. |
| [nvk/llm-wiki](https://github.com/nvk/llm-wiki/tree/d60674ff785e5c6d35322657d7839a7c0bdd3ca7), MIT | Multi-runtime wiki workflows. Tested query-lite in real Pi sessions and its session-state regression. | Useful read-only navigation and workflow reference. Do not treat the profile as a search-ranking engine. |
| [QMD](https://github.com/tobi/qmd), MIT code | Local SQLite search, embeddings and optional model-based expansion/reranking. Tested installed version 2.8.3. | Best tested search backend. Needs explicit Pi access and index freshness handling. |
| [Swarm template](https://github.com/The-Swarm-Corporation/Multi-Agent-RAG-Template/tree/daba170b359e13d968487e2efad6d1dd7510f60e), MIT | A medical-agent sequence using Swarms, Groq chat and LlamaIndex. Its memory class builds an index from a directory and queries it. | Not a persistent Pi wiki integration. No durable wiki editing or concurrent-write policy was found in the checked implementation. Not run. |
| [Metadata filtering](https://github.com/coleam00/cole-medin-knowledge-base/blob/eba5e31bc628280c546d4828491051c308d550dc/concepts/metadata-filtering.md), no repository license found | A concept page about source, time and provenance filters. It is not a backend. | Use the general idea, not copied text. Filters must not silently remove relevant cross-project evidence. |
| [Structured hierarchical retrieval](https://github.com/IkechukwuAbuah/Structured-hierarchical-Retrieval---RAG/blob/e9d3b1fdd3480b7fbf896f1a8f24693493de4c6b/Main), no repository license found | LlamaIndex tutorial with summaries, Weaviate collections, inferred metadata filters and recursive document retrieval. Uses OpenAI in the example. | A retrieval pattern, not a drop-in Pi wiki. Summary routing can miss an entire document. Benchmark before adding it. Not run. |
| [redmizt](https://github.com/redmizt/wiki-llm-for-multi-agent-builds/tree/d341658726f2e704229c715013ae26ac976acbc0), All Rights Reserved | Multi-agent wiki design and integrity hooks. The license permits public viewing but requires advance written permission for use or incorporation. The supplied gist metadata was also checked. | Reference only. Do not copy its hooks or templates without permission. |
| [Stash](https://github.com/Fergana-Labs/stash/tree/3691d14c4e1e5e5e18250d804e631ff6e5943aae), MIT | Persistent sessions, curated memory, skills, CLI/MCP/API. Local source setup provisions Postgres, Redis, a backend and workers. | Worth considering for a broader shared-memory service. More deployment work than this test needs. No performance claims independently verified. Not run. |
| [Newsroom](https://github.com/alfadur7/llm-wiki-newsroom/tree/8e209cab483da544852d7213f0e25291d06d8a88), MIT | Editorial roles, deterministic lint, separate qualitative review and regeneration workflows. Claude Code is its primary integration. | Reuse review practices when needed. Pi integration and retrieval recall remain untested. Do not adopt the entire workflow before proving its cost. |
| [MCP Memory Service](https://github.com/doobidoo/mcp-memory-service/tree/238e609e7804874a772d6711b8acbd06526c7c55), Apache-2.0 | Version 12.7.0 exposes persistent memory over REST/MCP. It provides local ONNX embeddings, SQLite-vec and hybrid retrieval. Checked storage code uses connection locks, retries and WAL. | A serious QMD alternative when shared database-backed memory fits the goal. Source and license reviewed only. Not installed, benchmarked or stress-tested here. |

## QMD is replaceable

MCP Memory Service can replace more than search. Its shared API could remove some custom persistence and multi-client integration work. It stores database memory records rather than maintaining the same curated Markdown wiki workflow.

Before writing a custom queue, test whether that service's document ingestion, source citations, project isolation and export behavior meet the wiki requirement. Repeat the same hard-query and concurrent-write tests. Database locks in source code do not establish end-to-end safety.

SQLite FTS5 is another measured alternative. It is simple, but its model-free control missed two hard questions. Adding embeddings and synchronization would require more integration code. QMD already supplies that machinery.

The user imposed no database ban. Neither Markdown nor QMD is a fixed architecture constraint. No alternative is called better without equivalent runtime evidence.

## Next implementation boundary

If the curated-wiki route is selected, the next build is a project-local integration, not another wiki framework:

- Keep cited Markdown pages and raw sources as the durable record. Treat the search database as rebuildable.
- Give readers and child agents the same explicit vault root and read-only retrieval tools.
- Offer lexical and vector candidates, then read exact cited files before answering.
- Route write proposals through one curator. Do not expose unrestricted capture or same-page replacement to parallel agents.
- Reindex after accepted writes. Preserve provenance, superseded decisions and explicit project scope.
- Test a real project corpus, negative-answer behavior, index freshness, restarts and the actual deployed subagent extension before production use.

Corpus size, resource limits and simultaneous-editing requirements still need agreement. No five-domain scheme, flat-file-only constraint or Raspberry Pi requirement is assumed.

## Reproduce

Python offline verification needs only the standard library. It works without Pi, candidate packages or model downloads:

```sh
python3 -m unittest discover -s research/tests -v
python3 research/score.py
python3 research/score.py --challenge
```

Integration reruns need Node 22, Pi 1.5.0, Pi LLM Wiki 0.12.5 and QMD 2.8.3. `research/lib.mjs` resolves the installed packages. Override `PI_PACKAGE`, `PI_WIKI_PACKAGE` and `QMD_PACKAGE` if they live elsewhere.

Prepare the pinned nvk checkout in ignored storage:

```sh
git clone https://github.com/nvk/llm-wiki.git .cache/upstreams/nvk
git -C .cache/upstreams/nvk checkout --detach d60674ff785e5c6d35322657d7839a7c0bdd3ca7
```

Rebuild the corpora and run the search modes in this order. The vector command downloads approximately 334 MB on its first run:

```sh
node research/run-retrieval.mjs
node research/run-retrieval.mjs --challenge
python3 research/sqlite-baseline.py
python3 research/sqlite-baseline.py --challenge
node research/run-vector.mjs
python3 research/score.py
python3 research/score.py --challenge
node research/run-concurrency.mjs
```

Corpus generation replaces only disposable candidate directories under `.cache/comparison`. Run it before persistence tests, not between save and reload.

Live runs require the named model and a `local-llamacpp` provider in Pi's `models.json`. The endpoint must use loopback or a private LAN address. The runner copies only non-secret settings and disables retries, MCP, global extensions and automatic context loading. Each call has a 150-second limit. Raw sessions remain ignored. Saved outcomes append to `results/live.json`.

```sh
for q in q05 q09 q12 q21 q22 q25; do
  python3 research/run-live.py zosma "$q"
  python3 research/run-live.py nvk "$q"
done
python3 research/run-live.py zosma save
python3 research/run-live.py zosma reload
node research/run-child.mjs
python3 research/run-live.py zosma read-child
```

`python3 research/fetch-sources.py` refetches pinned public source files and verifies their hashes. It does not execute them.

## Security and cleanup

The old `wiki/`, its plan and its research claims were removed. Credentials, access logs and bytecode were removed from tracking. The live login file remains intact. LAN services, tunnels and global Pi configuration were not changed.

**Do not publish the current Git history.** A previous commit contains a LAN password. Ignoring the file now does not remove it from history. Credential rotation and history cleanup remain separate, unperformed actions.
