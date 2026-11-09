# Grounding and constraints

This is a source-grounded model of the existing systems, not a claim that the proposed production system exists.

## Current state

Baseline commit `829f42b` contains experiments and no deployed wiki. [The recorded comparison](../../research/README.md) separates tiny-corpus retrieval scores, actual Pi sessions, a child-agent test and multi-process write losses. The new user request adds production design, bounded delivery and sequential Pi -> Codex -> Claude Code -> OpenCode support.

Unrelated `access/` work, running services and global agent configuration are out of scope. Existing repository history contains a credential and must not be published. The future application and knowledge vault need clean publication history.

## Observed runtime flow

1. Pi LLM Wiki registers Pi tools in `extensions/llm-wiki/index.ts` and `lib/tools.ts`. `wiki_retro` calls `lib/retro.ts:saveInsight`, writes a document and an event, then rebuilds or schedules metadata. `lib/source-packet.ts:captureText` allocates a directory through `lib/utils.ts:nextSequentialId`, writes extracted evidence and a manifest, then a source page.
2. `lib/metadata.ts:rebuildMetadata` discovers documents, builds registry/backlinks/index/log projections and atomically replaces each output file. This is not a transaction across the source write and all projections.
3. `lib/recall.ts:searchWiki` scores lexical fields. `searchWikiHybrid` optionally uses the package's own embedding sidecar. That native semantic mode was not benchmarked in the earlier research.
4. QMD `createStore` owns a separate search database. `update`, `embed`, `searchLex`, `searchVector` and `search` are distinct operations. A source write does not imply vectors are fresh.
5. Pi LLM Wiki already has `lib/qmd-store.ts:openQmdIndexStore`, with typed lexical/vector fusion and expanded/reranked search. `lib/qmd-indexing.ts:reindexQmdVault` has cross-process locking, mirror validation, copy-on-write staging and a journaled swap. `lib/qmd-mirror.ts` separates canonical knowledge from evidence. Reuse or adapt these before inventing another indexing lifecycle.
6. The package already ships `mcp/index.ts` and `dist/mcp/index.js`, a standalone stdio MCP server over the shared document model. Cross-client transport is not a missing concept that needs invention. The missing evidence is safe concurrent publication and the final application contract across real hosts.
7. A Pi SDK `SessionManager` owns one transcript. Its persistence does not share knowledge automatically. The wiki's `lib/subagent.ts:runSubAgent` starts a new agent loop with explicit messages and tools. The separate `pi-subagents` extension remains a different integration.

The earlier report's statement that no QMD-to-Pi adapter exists must be read as no completed, verified application integration in this repository. The installed package already contains QMD adapters, indexing recovery and an MCP server. This design must account for those existing components rather than duplicate them.

## Client path and version constraints

| Host | Observed version | Source-backed integration point | Release-time check |
|---|---|---|---|
| Pi | 1.5.0 | Native tools or `.pi/mcp.json`; MCP tool pipeline supports streamable HTTP and stdio. SDK needs explicit extension factories and `bindExtensions()` for MCP. | Assert active tools, then make a real parent and child call. `tools: []` disables custom tools too. |
| Codex CLI | 0.163.0 | Official MCP docs describe `[mcp_servers.name]` in configuration, streamable HTTP `url`, bearer token environment references and tool allowlists. | Validate against the installed CLI, then test independent sessions and native child behavior. |
| Claude Code | 2.1.310 | Official docs describe HTTP MCP, project/user scope, and `mcpServers`, `tools` and `disallowedTools` for subagents. | Test actual foreground/background children and trust/approval behavior. A built-in-only tool allowlist can remove all MCP tools. |
| OpenCode | 1.19.3 | Official current docs describe MCP and fresh-context child sessions. | Current web docs explicitly use V2 `mcp.servers`, `disabled` and ordered permissions. Do not assume those templates work with installed 1.19.3. Validate its schema before implementing this final adapter. |

The same absolute service identity and authenticated project scope must survive cwd/worktree changes. Do not derive the knowledge partition from cwd, model text, session ID or optional MCP metadata. A stdio server per client is a separate process, not automatically one publisher.

## What the evidence requires

- Preserve independent sessions and child agents as normal clients of durable knowledge, not as transcript-sharing tricks.
- Prevent duplicate logical writes and lost same-page updates. The saved stress run lost 23 of 96 concurrent captures and seven of eight same-slug writes.
- Distinguish durable proposal acceptance, committed knowledge and indexed visibility. An event or successful dispatch is not proof of all three.
- Give every citation a stable source revision. Treat search scores as ranking signals, never probabilities of truth.
- Make stale indexes observable. Revalidate every hit against authorized current state; do not silently discard newly committed knowledge because vector work is pending.
- Keep captured evidence separate from synthesized knowledge. Raw captures and retrieved instructions do not automatically become trusted project rules.

## Why these boundaries

Direct evidence for intent is the current user request, prior conversation and commit `829f42b`: reuse measured open-source components, remove unsupported claims, preserve live operations, avoid endless development and verify behavior in actual agents. The prior experiment supports a semantic retrieval requirement, but not a guaranteed production recall number.

The proposed single publication authority and revision-scoped reads are design choices derived from the observed races. They are not claims about upstream authors' intent. A database is permitted; Markdown-only storage and QMD were never user constraints.

Source control and local documents were available. No issue-tracker, team-chat, observability, exception-tracking or analytics MCP tools were exposed. Those organizational rationale sources are unavailable, not searched-and-empty. Context7 was also unavailable; client facts come from fetched official documentation rather than recalled API syntax.

## Independent grounding and setup failure

Two read-only SDK children inspected source paths and returned explanations, using configured `gpt-6-luna`. Their first attempts had an empty tool allowlist and no reads. Those outputs were rejected. One corrected retry per child used an allowlisted `evidence_read` tool and completed with 14 and 19 source reads. This was analysis, not production-host verification.

The supervisor checked the extra QMD/MCP source paths after those reports. This found additional reuse opportunities and corrected the too-broad reading of the previous recommendation. The architecture phase must retain that correction.

## Reuse boundaries

Pi LLM Wiki, nvk and QMD code have MIT licenses. MCP Memory Service has Apache-2.0. Preserve notices and pin versions/source hashes for any extraction or fork. Do not copy redmizt hooks or templates, which are All Rights Reserved. Embedding weights require their own license and evaluation gate.

Prefer existing parsing, document formats, MCP transport, retrieval, index recovery and SQLite transactions. The new code must own only application invariants not supplied by those components. A source review is not a safety certificate for any dependency.
