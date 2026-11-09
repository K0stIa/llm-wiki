# Agent Wiki — multi-agent, high-recall knowledge base

Five specialized wiki domains, each with its own access model and update cadence.
No database, no embedding service — flat files, two-stage recall, cascading updates.

## Architecture (5 domains)

```
wiki/
├── wiki_rules/          → Framework protocols, pipeline rules, skill enforcement
├── wiki_domain/         → Domain-specific knowledge base (entities, concepts)
├── wiki_memory/         → Session memory: user preferences, collaboration model
├── wiki_insights/       → Crystallized learnings: observed patterns, active analysis
├── wiki_sources/        → Historical archive: conversation transcripts, past artifacts
├── meta/                → Registry, backlinks, log (generated)
├── raw/                 → Immutable source packets
├── hooks/               → Pre-tool integrity hooks (file-based)
└── scripts/             → Lint, dedup, context compile, graph
```

## Access cadence (why 5 domains exist)

Different domains have different access patterns. Loading irrelevant rules into every
session is the #1 cause of context-window exhaustion in multi-agent wikis.

| Domain | Loaded when | Loaded by whom |
|--------|-------------|----------------|
| `wiki_rules` | Before writing, before committing | All agents that write |
| `wiki_domain` | Before describing entities | Content creators + evaluators |
| `wiki_memory` | Session start (cold start) | All agents |
| `wiki_insights` | Selectively, by topic | All agents |
| `wiki_sources` | Only for audit/forensics | Operator, orchestrator |

## Two-stage recall

Small vault (≤50 pages): returns inline content previews.
Large vault (>50 pages): returns ranked links only — `id`, `title`, `type`, `score`, 1-line snippet.

Two-step contract for large vaults:
1. **Stage 1 — scan links.** Pick the few pages that matter.
2. **Stage 2 — expand on demand.** Read chosen pages before relying on them.

## Naming convention

`YYYYMMDDNN` base format with type codes:

```
Dispatch:  2026110901-D0047
Insight:   2026110901-I003
Source:    2026110901-S012
Migration: 2026110901-M01
```

22 type codes cover every artifact class. Lexicographic sort = chronological sort.

## Capability tokens

File-based identity tokens (persist between Bash calls, unlike env vars):

```yaml
# .pi/session_identity/agent-name/current.txt
agent: agent-name
session_id: "2026110901"
groups: [all, creative, domain-readable]
hard_walls: [.overlord_vault/, wiki_domain/sealed/]
sha256_checksum: "..."
```

## Pages

Each page is one file. One concept = one page. Every page has frontmatter:

```yaml
---
type: entity | concept | insight | source
created: 2026-11-09
updated: 2026-11-09
sources: [SRC-2026110901-001]
---
```
