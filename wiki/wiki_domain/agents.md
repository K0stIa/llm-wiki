---
type: entity
category: agents
created: 2026-11-09
updated: 2026-11-09
domain: agents
---

# Agents

Agents operating in this project. Each agent has a capability token (file-based identity) and a defined scope.

## Agent roles

| Agent | Role | Groups | Scope |
|-------|------|--------|-------|
| orchestrator | Fleet coordinator, wiki routing | all | Full read/write |
| content-creator | Writes wiki pages, ingests sources | creative, domain-writable | wiki_domain, wiki_insights |
| evaluator | Quality review, scoring | evaluation | wiki_domain (read-only) |
| operator | Human-in-the-loop, final decisions | all | Full read/write |

## Capability tokens

Each agent's identity is a YAML file under `~/.pi/session_identity/<agent>/`.
Tokens persist between Bash tool calls (unlike env vars).

See `[wiki_tokens.py](/wiki/scripts/wiki_tokens.py)` for the token system.

## References

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — original pattern
- [redmizt/wiki-llm-for-multi-agent-builds](https://github.com/redmizt/wiki-llm-for-multi-agent-builds) — multi-agent extensions
