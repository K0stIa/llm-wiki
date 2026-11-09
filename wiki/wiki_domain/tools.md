---
type: entity
category: tools
created: 2026-11-09
updated: 2026-11-09
domain: tools
---

# Tools

Tools available to agents. Each entry has: name, capability, limitations, and when to use it.

## Models

- **qwen3.8-35b-a3b-mtp-256k** — Primary local model. 256K context. Used via llama-swap.
- **llama-swap** — Model routing/proxy. Switches between models.

## Agents

- **Pi (1.5.0)** — Primary agent. Multi-domain wiki, trajectories, skills.
- **OpenCode (1.19.3)** — Secondary agent. Web-based UI.
- **Sub-agents** — Delegated parallel tasks via pi's subagent dispatch.

## Tools

| Tool | Purpose | Access model |
|------|---------|--------------|
| `wiki_recall` | Two-stage recall (small→inline, large→links) | All agents |
| `wiki_compile` | Budget-aware context compilation | All agents |
| `wiki_cascade` | Cascading update after ingest | Content creator |
| `wiki_lint` | Health check (orphans, missing links, stale) | All agents |
| `wiki_tokens` | Capability token management | Operator |
| `read` / `grep` / `find` | Basic file ops | All agents |

## References

- [nvk/llm-wiki](https://github.com/nvk/llm-wiki) — multi-runtime wiki packaging
- [Fergana-Labs/stash](https://github.com/Fergana-Labs/stash) — experience-to-skill pipeline
- [alfadur7/llm-wiki-newsroom](https://github.com/alfadur7/llm-wiki-newsroom) — cascading updates, contradiction tracking
