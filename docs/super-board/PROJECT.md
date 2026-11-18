# LLM Wiki

LLM Wiki is an unreleased shared knowledge service for coding agents. Python owns the transactional SQLite authority. TypeScript handles retrieval and host transport. The authority generates Markdown exports and applies changes through proposal, review, and publication.

| Area | Location |
|---|---|
| Design, contracts, and release gates | [specs/wiki-system](../../specs/wiki-system/) |
| Authority, retrieval, and host integrations | [src](../../src/) |
| Runtime and property tests | [tests](../../tests/) |
| Wiki and retrieval research | [research](../../research/) |

Use the private GitHub Project to collect and triage findings for `K0stIa/llm-wiki`. The configured base branch is `super-board/implementation`, and merges require human approval. [LLM Wiki Backlog](https://github.com/users/K0stIa/projects/1)

This source snapshot is the proposed implementation base. Dispatch waits for the owner to approve publication and for the base to exist on GitHub. The original checkout remains available for private evaluation work. Follow the repository's rules for verification budgets and release evidence. [Repository instructions](../../CLAUDE.md)
