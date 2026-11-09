# Agent Wiki — high-recall multi-agent knowledge base

Five specialized wiki domains, two-stage recall, cascading updates, capability tokens.
No database, no embedding service — flat files, works with local models.

## Quick start

```bash
cd wiki
python3 scripts/wiki_recall.py --query "agent architecture"
python3 scripts/wiki_compile.py --budget 2000 --domains wiki_rules,wiki_domain
python3 scripts/wiki_lint.py
```

## Structure

```
wiki/
├── wiki_rules/          → Rules, protocols, enforcement
├── wiki_domain/         → Entities, concepts, tools
├── wiki_memory/         → Session memory (T1/T2/T3)
├── wiki_insights/       → Active learnings, spark field
├── wiki_sources/        → Immutable source packets
├── meta/                → Registry, index, log
├── raw/                 → Raw source packets
├── hooks/               → Pre-tool integrity hooks
└── scripts/             → Recall, compile, lint, cascade, tokens
```

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| 5 domains, not 1 | Context windows are tight; loading irrelevant rules is fatal |
| Two-stage recall | Links-first for >50 pages saves the context budget |
| No vector search | No embedding service; BM25-style on flat files |
| Cascading updates | One ingest refreshes 10-15 pages — the compounding effect |
| Capability tokens as files | Env vars die between Bash tool calls (documented in redmizt) |
| YYYYMMDDNN IDs | Globally unique, sortable, greppable, no central authority needed |

## Research basis

- Karpathy's LLM Wiki pattern (original three-layer)
- redmizt/wiki-llm-for-multi-agent-builds (25 extensions for multi-agent)
- nvk/llm-wiki (multi-runtime packaging, two-stage recall)
- Fergana-Labs/stash (experience → skills pipeline)
- alfadur7/llm-wiki-newsroom (cascading updates, contradiction tracking)

See `RESEARCH_FINDINGS.md` for the full survey.
