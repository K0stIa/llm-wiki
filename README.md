# Shared knowledge for coding agents

Design and measured research for a knowledge system shared by independent coding-agent sessions and actual child agents. No replacement service or production host integration is implemented.

The design is ready for implementation. SQLite owns durable evidence, reviewed revisions and operation receipts. Markdown and retrieval indexes are derived. QMD is the initial semantic retrieval backend, not a permanent requirement.

## Start here

- [Design status and index](specs/wiki-system/README.md)
- [Architecture and usage](specs/wiki-system/ARCHITECTURE.md)
- [Typed API contract](specs/wiki-system/contract.d.ts)
- [Bounded implementation plan and runtime gates](specs/wiki-system/DELIVERY.md)
- [Independent closure review](specs/wiki-system/arena/closure-review.md)
- [Verification scope and recorded evidence](specs/wiki-system/VERIFICATION.md)
- [Measured candidate comparison and synthetic research](research/README.md)

Implementation starts with P0. Host integration proceeds strictly through Pi, Codex CLI, Claude Code, then OpenCode. Runtime gates G0-G8 have not been run. Design approval is not production certification.

## Check the saved evidence

These commands need only Python's standard library. They do not call models, download weights or start services.

```sh
python3 -m unittest discover -s specs/wiki-system/tests -p 'test_*.py' -v
python3 -m unittest discover -s research/tests -v
python3 specs/wiki-system/verify.py
python3 specs/wiki-system/verify.py --require-ready
```

The contract tests use TypeScript 5.9.3. Historical `.cache/` compiler paths in the evidence refer to the source workstation and are not distributed. Integration reruns require the pinned tools and approved local model setup described in [the research report](research/README.md#reproduce).

## Publication provenance

This repository starts with a new, parentless publication commit. It contains byte-identical copies of `specs/wiki-system/` and `research/` from source commit `64ad9261d76e0dba8376dae4520747ca3cc7998d`, plus this README and `.gitignore`.

The source Git history, access tooling, credentials, logs, host configuration, model weights and raw sessions are excluded. Warnings in preserved reports about credential-bearing Git history refer to the private source repository, not this new publication history. This export does not rotate that credential or repair the private repository's history.

Upstream code and embedding weights have separate license requirements. No model weights are redistributed. The design's licensing and deployment gates still apply.
