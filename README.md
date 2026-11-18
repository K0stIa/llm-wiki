# Agent UI sandbox and wiki evaluation

This repository holds local agent-access tooling and a comparison of shared wiki solutions for Pi sessions and child agents.

The previous custom wiki prototype was removed. It did not establish high recall or safe concurrent writes. No replacement wiki is deployed.

## Wiki findings

Read [the measured comparison](research/README.md) for results, source licenses and rerun commands.

QMD vector retrieval handled the tested paraphrases that lexical recall missed. Pi LLM Wiki passed session-to-session and child-agent persistence checks, but concurrent capture lost source contents. For a curated wiki, the tested direction is existing Pi integration, semantic retrieval and one writer. QMD is optional. MCP Memory Service is a reviewed alternative for shared database-backed memory, but it has no runtime scores here. No route is a production configuration yet.

Verify the saved evidence without models or network access:

```sh
python3 -m unittest discover -s research/tests -v
```

## Production design

[The wiki/RAG design](specs/wiki-system/README.md) chooses a transactional knowledge authority with generated Markdown exports and reusable semantic retrieval. It includes a type contract, bounded prototype gates and sequential Pi, Codex CLI, Claude Code and OpenCode verification. This is a design, not a deployed replacement.

## Existing access setup

The access tooling is separate from the wiki experiments. Its launchers remain available:

| Launcher | Documented local interface |
|---|---|
| `opencode-web-test` | `http://127.0.0.1:4096` |
| `pi-tui-test` | Local Pi terminal |
| `pi-web-test` | `http://127.0.0.1:7682` |

See [the access plan](access/PLAN.md) before changing routes or running network checks. This research did not restart services, change tunnels or verify their current health.

## Private files and Git history

Keep credentials, raw sessions, model weights and generated indexes out of Git. Research uses ignored `.cache/` directories.

**Do not publish this repository's current history.** An earlier commit contains a LAN password. The live file remains intact but is no longer tracked. Credential rotation and history cleanup have not been performed.
