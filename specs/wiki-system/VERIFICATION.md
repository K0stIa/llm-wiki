# Design closure verification

Scope: the design, declaration contract and executable document/review checker. No knowledge service, deployed MCP endpoint or host adapter is implemented. Runtime G0-G8 remain unrun.

## Current checks

| Check | Observed result |
|---|---|
| Baseline | Strict contract compilation, 10 checker tests and 14 research tests passed before this change set |
| Checker red phase | New regressions reproduced contradictory/duplicate/example verdict acceptance, receipt disagreement and missing checker/test source binding |
| Checker green phase | All 17 unit tests pass, including current snapshot and fail-closed cases |
| Contract red phase | Rejection required an attestation, journal type was absent and curator propose was allowed |
| Contract green phase | TypeScript 5.9.3 strict/noEmit passes complete reads/review, key-free journal intents and metadata rejection |
| Negative type control | Removing 12 expected-error annotations produces 12 actual compiler diagnostics |
| Service behavior | Not tested or claimed |
| Fresh independent closure review | Anthropic `claude-opus-5-5`, high reasoning: READY-FOR-IMPLEMENTATION, no must-fix findings, 9 reads |
| Final readiness gate | `python3 specs/wiki-system/verify.py --require-ready` exits 0 |

Commands, exits and source/output hashes are recorded in [validation.json](validation.json). The [prior local validation](arena/pre-closure-validation.json) is retained, not relabeled as evidence for the new snapshot. [The ledger](OPUS_FIXES.md) maps all findings to changes and their proof boundaries.

## What is and is not established

Type tests show the API can express rejection without a review attestation while still requiring the attestation for publication. They exercise typed durable-prepare calls and prevent curator proposal calls through the declared client. Runtime server authorization is a separate G3 test, not something client types prove.

The checker requires one exact leading verdict, matching review metadata and any receipt verdict. It verifies provider/model/high/completed identity, report hash and current hashes for architecture, contract, delivery, checker and both test files. Conflicting/duplicate/example-only verdicts, changed reviewed source and malformed metadata cannot yield READY. Historical reports never override the latest status.

The architecture specifies the full lifecycle, transactional unresolved-slot release and default metadata-only rejection housekeeping. G1/G3 will test a full blocked backlog, admission after rejection, late-review races, preservation and restart against a real service. The current document checker checks structure, not those behaviors. No simulator is substituted for the service.

The 14 research tests concern previously recorded experiments, not this unimplemented system's recall, concurrency, isolation, restore or actual host-child behavior.

## Reproduce

```sh
python3 -m unittest discover -s specs/wiki-system/tests -p 'test_*.py' -v
python3 -m unittest discover -s research/tests -v
node .cache/architecture/typecheck/node_modules/typescript/bin/tsc \
  --noEmit --strict --target ES2022 --module NodeNext --moduleResolution NodeNext \
  specs/wiki-system/tests/contract.test.ts
python3 specs/wiki-system/verify.py
python3 specs/wiki-system/verify.py --require-ready
```

`--require-ready` passed after the [fresh Opus closure review](arena/closure-review.md) approved the snapshot. The [receipt](arena/closure-review.json) matches all six decision-critical file hashes; an altered core file invalidates that approval. The isolated compiler is already installed; no new dependency, model or global configuration is needed.

## History and limits

Original candidate, synthesis and Opus reports remain unchanged in `arena/`. Earlier READY verdicts apply only to their historical snapshots. The previous one-pass stopping rule was assistant-imposed, not a user requirement.

The current user authorized one consolidated repair/verification change set. One repair round and one Opus call completed it, within the two-round/two-call working budget. No must-fix finding was waived. The review's four nonblocking notes have explicit dispositions in the ledger; no second review loop was started. Status-note updates after review do not alter its six frozen decision-critical files.

Design closure is complete. Next is P0; this is not permission to deploy or skip runtime gates. No commit, push, history rewrite, credential operation or service restart occurred.
