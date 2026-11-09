# Plan: High-Recall Multi-Agent Wiki

## What was built (Phase 1 — done)

**Five domains, two-stage recall, cascading updates, capability tokens.**

- `wiki/` — five-domain skeleton with content pages (agents, tools, session memory, rules)
- `scripts/wiki_recall.py` — two-stage recall (≤50 pages inline, >50 pages links-first)
- `scripts/wiki_cascade.py` — cascading update (one ingest refreshes 10-15 pages)
- `scripts/wiki_compile.py` — budget-aware context compilation (2000 token default)
- `scripts/wiki_lint.py` — health check (orphans, broken links, stale pages)
- `scripts/wiki_index.py` — registry builder (scan pages, write registry.json + index.md)
- `scripts/wiki_tokens.py` — file-based capability tokens (replaces env vars)
- `wiki/hooks/` — integrity hooks (access group, clean-read mode sentinels)
- `RESEARCH_FINDINGS.md` — 10-project landscape survey with analysis

## Design decisions

1. **Five domains, not one** — Different access cadences prevent context pollution. Rules loaded before writing. Memory loaded at session start. Insights read selectively. Sources archived.
2. **Two-stage recall** — Small vault (≤50 pages) returns inline previews. Large vault returns ranked links. The two-step contract (scan → expand) protects the context budget.
3. **No vector search** — No embedding service. BM25-style keyword scoring on frontmatter + title. Sufficient for 100-page wikis.
4. **Cascading updates** — The compounding effect that makes a wiki worthwhile vs. just piling up pages. One new source touches 10-15 pages.
5. **Capability tokens as files** — Documented in redmizt's report: env vars die between Bash tool calls. Files persist.
6. **YYYYMMDDNN IDs** — Globally unique without a central authority. Lexicographic sort = chronological. Greppable.

## Phase 2 — next (skill distillation + trajectories)

- `raw/trajectories/TRJ-*/` — immutable task packets (tool-call sequences)
- `wiki/cases/` — one case per trajectory
- `wiki/skills/` — distilled reusable patterns
- `wiki_recall_skill()` — "have I done this before?" at task start
- The stash/Fergana-Labs pattern: correction → durable lesson → reusable skill → next agent loads it

## Phase 3 — capability tokens + multi-session identity

- Per-agent tokens in `~/.pi/session_identity/`
- `hard_walls` — permanently invisible paths (like `.overlord_vault/`)
- `contamination_quarantines` — temporarily invisible content (evaluation isolation)
- Cross-session identity: agent token survives Pi session restart

## Phase 4 — knowledge graph (Leiden clustering)

- Wikilink-based graph → Leiden community detection → auto-clustering
- Interactive graph HTML (like llm-wiki-newsroom)
- Contradiction tracking (3 layers: macro summary → theme → raw evidence)

## What to skip

- 194 hooks (redmizt's full fleet) — overkill for a single-project wiki
- Newsroom meta loop (evolving authoring guidelines) — expensive on local model; keep the idea but simplify
- Conversation capture hooks — need to verify Pi supports UserPromptSubmit hooks before implementing
