# Architecture workflow

User request: design a production LLM-wiki/RAG system for shared coding-agent knowledge, with bounded development and staged Pi, Codex, Claude Code and OpenCode support.

## Architect phases

- [x] Ground: traced wiki, retrieval, persistence and host integration. Corrected the missing-native-MCP/QMD assumption. See GROUNDING.md.
- [x] Sketch: two structurally distinct candidates, independent cross-judge and supervisor red-flags screen. See RATIONALE.md and arena/.
- [x] Agree: chose database authority autonomously. No extra human design checkpoint was added.
- [x] Implement the requested design contract: produced contract.d.ts, architecture and bounded implementation units. Runtime application implementation has not started.
- [x] Scrap check: no implemented architecture exists to scrap. One design-review correction fixed snapshot, replay, authorization and type ambiguities. Repeated implementation friction remains a future redesign trigger.

## Arena phases

- [x] Frame the task and six-criterion rubric.
- [x] Fan out document-authoritative and database-authoritative candidates into separate files. Each first attempt timed out; each completed on its one bounded retry.
- [x] Cross-judge completed candidates with a fresh reviewer.
- [x] Pick B after reading both candidates end to end. Supervisor and judge agree.
- [x] Graft snapshot-bound retrieval and concrete reuse obligations from A. Record rejections and limitations.
- [x] Verify the synthesized design. A fresh reviewer requested revision; the one correction/rerun ended READY-FOR-IMPLEMENTATION, not production certification.

The user asked for a design and development/testing process. This run produces that design and its implementation contract, not a silent production deployment or all four integrations at once. Agent support must progress Pi -> Codex CLI -> Claude Code -> OpenCode.

## User-requested Opus repair

- [x] Confirm: reproduce missing contract features with red compiler tests and inspect every review item. Preserve the original report.
- [x] Fix: full-page review, curator identity/discovery, restore epochs and the supporting gaps. See OPUS_FIXES.md.
- [x] Verify: strict TypeScript tests, 10 checker tests and 14 research regressions pass. That earlier Anthropic Opus 5.5 high-reasoning review confirmed the original fixes but found the blocked-proposal lifecycle gap. Its historical verdict was NEEDS-REVISION.

The earlier one-pass cap was imposed by the assistant, not the user. The latest request explicitly authorizes the consolidated repair/verification change set. No service deployment is included.

## Current design closure

- [x] Freeze architecture and confirm M1, checker V1 and the five known clarifications.
- [x] Add failing checker/contract regressions, then apply the minimal coherent fixes.
- [x] Align lifecycle, server role policy, host journal type, restore identities and FTS citation granularity across the contract/architecture/delivery files.
- [x] Final local checks and fresh source-bound Opus verification pass. [Closure report](arena/closure-review.md): READY-FOR-IMPLEMENTATION, no remaining must-fix. `verify.py --require-ready` exits 0.

Used one consolidated repair round and one independent Opus call, within the two-round/two-call budget. No architecture contest, threshold relaxation or second review was needed. The six decision-critical files are unchanged from the reviewed snapshot; only status/evidence notes were finalized afterward. Four nonblocking follow-ups are recorded rather than reopening closure.

Next: P0, not production rollout. Runtime G0-G8 remain unrun. No service, model download, global client configuration, commit or publication was added.
