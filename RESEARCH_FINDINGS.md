# LLM Wiki for Multi-Agent Pi Sessions — Research Findings

## What the user wants

A wiki with **high recall**, that works across **sub-agents** and **different Pi sessions**, for a project running on a small Pi server with a local Qwen3.8-35B model.

## The problem statement

Karpathy's original LLM Wiki pattern (3 layers: raw sources → wiki → schema) assumes one user, one agent, sequential access. Our environment has:
- Multiple Pi sessions running in parallel (Web + TUI + sub-agents)
- A single local LLM (qwen3.8-35b) with 256K context — tight for recall
- No vector DB or embedding service — everything must work on flat files
- Different agents reading/writing the same wiki simultaneously

## Landscape survey (10 projects found)

### Tier 1 — directly relevant

| Project | Stars | What it brings |
|---------|-------|----------------|
| **redmizt/wiki-llm-for-multi-agent-builds** | (private repo) | Multi-agent identity (capability tokens), 5 wiki domains with per-domain access cadences, YYYYMMDDNN IDs, 3-layer content protection, conversation capture as institutional memory, 194+ integrity hooks, deception detection. The most complete multi-agent adaptation of Karpathy. |
| **nvk/llm-wiki** | 1518 | Multi-runtime packaging (Claude Code, Codex, OpenCode, **Pi**, DS4). Two-stage recall (links-first for large vaults). Per-topic specialist framework. Project knowledge checkpoints. Query-lite profile (~2.8KB read-only). The reference for how to ship a wiki skill that actually reaches different agents. |
| **alfadur7/llm-wiki-newsroom** | 172 | Five-role newsroom (Reporter → Columnist → Copy Editor → Desk → EIC). **Evolving authoring guidelines** via a meta loop (107 amendments adopted over 13 weeks). Cascading updates (one ingest refreshes 10-15 pages). Knowledge graph with Leiden clustering. Contradiction tracking (3 layers). |
| **Fergana-Labs/stash** | 342 | **Agents learn from experience**: trace capture → durable lessons → reusable skills. A correction becomes a checklist that the next agent loads. 49% speedup for long-running agents in one experiment. |

### Tier 2 — structural patterns

| Project | Stars | Relevance |
|---------|-------|-----------|
| **SouthpawIN/bot-wiki** | 45 | Fleet of bots in markdown. No database, markdown API. Per-bot continuity, skills, loops. Shows how to scale wiki structure beyond one agent without a DB. |
| **TermHive** | 72 | Project wiki per project. Auto-generated `CLAUDE.md`/`AGENTS.md` with wiki paths. Per-project knowledge, not global. |
| **LCccode/Karpathy-wiki-graph** | 6 | Interactive knowledge graph on flat files. CLI-atomic. |
| **Local Pi skill** (`@zosmaai/pi-llm-wiki`) | bundled | Four-layer vault, trajectories (working-memory), skill distillation, two-stage recall, query-lite profile. Already a good baseline. |

## What works, what doesn't

| Pattern | Works at our scale | Why |
|---------|-------------------|-----|
| Multi-domain wiki (5 domains) | ✅ | Context windows are tight; loading irrelevant rules into every session is fatal. |
| Capability tokens (file-based, SHA256) | ✅ | Env vars die between Bash tool calls (we saw this in redmizt's report). Files persist. |
| YYYYMMDDNN IDs | ✅ | Globally unique without a database. `ls` sort = chronological. Greppable. |
| Two-stage recall | ✅ | Our model has 256K but we're already loading 30KB of wiki index at session start. Links-first saves context. |
| Cascading updates | ✅ | One new source touching 10-15 pages is the compounding effect that makes the wiki worthwhile. |
| Skill distillation from trajectories | ✅ | This is how sub-agents carry knowledge across sessions — distill a skill page, load it as a skill in the next session. |
| Three-layer content protection | ⚠️ | We need only Layer 2 (group-based) for multi-session. Layer 1 (hard walls) is overkill for a single-project wiki. |
| Newsroom / evolving guidelines | ⚠️ | Meta loop is powerful but expensive on a local model. Keep the idea but simplify the loop. |
| Vector search (qmd) | ❌ | No embedding service. Use BM25-style keyword search (qmd is local but needs a model). |
| 194 hooks | ❌ | We don't have a Claude Code hook framework here. Keep the ideas as documentation, not implementation. |
| Conversation capture | ⚠️ | Possible with hooks but we need to check if Pi supports UserPromptSubmit hooks. |

## Design decisions for this project

1. **Five domains, not one.** `wiki_rules/`, `wiki_domain/`, `wiki_memory/`, `wiki_insights/`, `wiki_sources/`. Each agent loads only what it needs.
2. **Two-stage recall.** Small vault → inline content. Large vault → ranked links only. Default threshold 50 pages.
3. **Query-lite profile** (~2.8KB) for read-only sessions. The full profile (~60KB) for write sessions.
4. **Cascading updates** on ingest: a new source updates existing entity/concept pages automatically.
5. **Skill distillation**: trajectories (task tool-call sequences) → distilled skill pages → loaded as skills in future sessions.
6. **No vector search.** Use BM25-style keyword search via the `qmd`-style index or simple grep with the registry.
7. **Capability tokens** for sub-agent identity, persisted as files (not env vars).
8. **Concurrent-safe**: file-based locks with TTL expiry for write contention.

## What to build first

Phase 1: Core wiki skeleton — 5 domains, two-stage recall, query-lite, ingest → cascading update, contradiction tracking.
Phase 2: Skill distillation + trajectories.
Phase 3: Capability tokens + multi-session identity.
Phase 4: Knowledge graph (Leiden clustering on flat-file wikilinks).
