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
