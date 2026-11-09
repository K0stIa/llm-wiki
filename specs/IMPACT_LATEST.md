---
type: impact
context: wiki-comparison
---

# Impact of the research reset

## Target

Remove the unvalidated wiki prototype and replace its claims with reproducible comparison evidence. This is research, not deployment of a replacement wiki.

## Dependents

The six prototype Python scripts refer to their local registry and each other only through documentation. No project Pi extension, registered tool, scheduled job or tests call them. The README, PLAN.md and RESEARCH_FINDINGS.md claim capabilities the prototype does not supply. Those documents will be replaced.

The unrelated access/ scripts read access/login.json from disk. Removing that file from the Git index must leave the local file intact. Do not change LAN services, credentials, forwarding or global Pi configuration.

## Affected stories

No release plan or story registry exists. The current user request authorizes removal of the prototype and evaluation of existing wiki tools, retrieval, independent sessions, child agents and concurrent writes.

## Test coverage

The prototype has no tests. New comparison scripts will have explicit expected page IDs, metric checks, per-run provenance and isolated storage. Live tests must use synthetic data, bounded local-model calls and separate session directories.

## Risk: Medium

Prototype removal is reversible through local Git history. The history itself contains a credential and must not be published as-is. The current tracked credential will be removed without deleting the live file. Credential rotation and history rewriting remain separate security actions and will not be silently performed.

## Recommended action

Proceed with an isolated research workspace. Do not install a production wiki or modify installed candidates. Report model downloads, comparison results and remaining gaps before recommending an architecture.

The subsequent experiment announced and downloaded one 334 MB embedding model into ignored storage. It used CPU execution. No expansion model or reranker was downloaded. The [completed comparison](../research/README.md) records this change and the remaining deployment gaps.

## Current task: repair confirmed Opus design gaps

Target: the unpublished `specs/wiki-system/contract.d.ts`, architecture, delivery gates and verification metadata. Dependents are the usage/rationale/status documents and the offline checker. No application imports this contract, no deployed store exists, and there is no release-story registry. Historical candidate/review artifacts remain immutable.

Risk: Medium. These are breaking changes to an unpublished shared API, not a production migration. The old checker only tested presence and a historical READY string. Add compiler-backed positive/negative contract tests and current-review/snapshot checks before declaring design readiness. Preserve unrelated access files, services and credentials.

Confirmation: the new TypeScript tests fail against the old contract for missing full-page reads, queue inspection, review digests and epoch-scoped barriers. The existing 14 research tests pass. One isolated TypeScript 5.9.3 development compiler is installed under ignored `.cache/architecture/typecheck`; no application/global dependency changed.

### Current closure change set

The user has authorized the consolidated repair and verification. Fix the blocked-proposal lifecycle and contradictory-verdict checker, plus the five recorded clarifications. Contract callers are its compile-only tests and architecture examples; checker callers are its unit tests and documented CLI commands. No application imports or deployed migrations are affected. Keep the SQLite/QMD/curator choice and all historical reports. Add red regressions before the fixes, run compiler/checker/research checks, then freeze the reviewed source hashes for fresh Anthropic Opus 5.5 high-reasoning verification. Working budget: at most two repair/test rounds and two review calls, not an unbounded design loop. This is a local execution budget, not a historical user-imposed one-pass restriction. Runtime G0-G8 remain unrun. No auto-commit or publication is included.
