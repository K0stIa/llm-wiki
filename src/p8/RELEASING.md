# Wiki release requirements

## Current status: release blocked

No release is authorized. Config checks, passing regression tests and operator acceptance of limitations do not satisfy DELIVERY's runtime acceptance gates.

The execution-budget audit STOP remains in force. Remaining authorized iteration and working-time balances could not be reconstructed. This documentation correction grants no experiment, retry, budget reset or release permission.

Do not run tests, benchmarks, model calls or release commands under this document. Further experiments require demonstrated remaining authorized budget or an explicit new owner-approved budget.

Paths below are relative to the repository root:

- Acceptance and execution limits: `specs/wiki-system/DELIVERY.md`.
- Recorded runtime evidence and limitations: `.verification/EVIDENCE.md`.
- Latest recorded self-check: `.verification/p34-verifier.txt`, exit 2, INCOMPLETE.
- Last tested source manifest: `.verification/p34-copy.json`.

The last full regression run reported 156 passing tests. It predates these documentation corrections. No tests were rerun for this update, and the old manifest does not certify the newly edited documentation.

**Update 2026-11-15:** the owner approved a per-phase budget ([DECISIONS.md](../../specs/wiki-system/DECISIONS.md) D1). Phases E (evaluation set) and P (local retrieval/answers) are approved. Host runs, isolation and G8 still need approval at phase start. Release remains blocked. Gate status is now computed from receipts: `python3 src/verification/check_gates.py`.

## Gate status

No complete G0–G8 release pass is established.

| Gate | Recorded evidence and remaining gap |
|---|---|
| G0: baseline and evaluation design | Answer profile and corpus artifacts exist. Independent labeling, a genuinely pre-frozen representative holdout and complete G0 acceptance remain unestablished. |
| G1: durable authority | Real durability, CAS and receipt regressions exist. The complete gate, including durable host-call journal recovery, is not established. |
| G2: retrieval and answers | Hybrid retrieval is exercised. Full holdout, answer-quality and concurrent performance/visibility acceptance remain open. |
| G3: security and operations | Scoped MCP denials and real temporary SQLite backup/restore are exercised. Production OS/credential isolation, backup cadence and production recovery objectives remain unverified. |
| G4: Pi | Real native wiki-child and fresh-session calls are recorded. This demonstrates that path, not the complete host gate or required host evaluation subset. |
| G5: Codex CLI | Native child execution exists. Actual parent and child wiki MCP calls were denied by the existing approval policy. Wiki integration remains blocked. |
| G6: Claude Code | A native child attempt is recorded. The wiki parent call was denied before wiki-child launch. Wiki integration remains blocked. |
| G7: OpenCode | The observed toolset exposed no native child launcher. The required native-child wiki gate remains unverified. |
| G8: independent final review | Unperformed. Implementer checks and watchdog feedback are not independent G8 approval. |

The installed versions are **Pi 1.5.0** and **pi-subagents 0.84.0**. They are different packages. The earlier claim that child execution was impossible because pi-subagents 0.12.5 lacked an API is obsolete.

Real Pi evidence includes:

- `.verification/runtime/pi-wiki-child-session.jsonl`.
- `.verification/runtime/pi-wiki-fresh.jsonl`.
- `.verification/runtime/pi-wiki-curator-publication.json`.
- `.verification/runtime/pi-wiki-validated-evidence.json`.

Those traces record native child page/propose calls, separate curator publication and fresh-session retrieval. They do not close the other G4 requirements or establish another host's gate.

## Open G2 requirements

The six saved hybrid measurements each use 36 serial queries. They do not establish the required run of at least 100 timed queries with ten concurrent readers, overlapping writes and committed-to-hybrid visibility measurement.

The earlier answer run produced gold-cited extracts for 8 of 28 positive questions. It used lexical retrieval before hybrid integration. It is not a post-hybrid answer result or a supported-answer gate pass.

A post-hybrid answer check using the same approved local Qwen profile remains unexecuted. The model, thinking setting, tokenizer, input/output budgets and acceptance thresholds are unchanged. Scope eligibility does not supply execution budget.

The frozen-corpus limitations and missing independent evaluation oracles remain blockers. Retrieval recall and exact citation resolution alone do not establish answer correctness, support or calibrated abstention.

## Requirements for any future release

This checklist records existing requirements, not permission to execute them now.

- [ ] Establish authorized execution budget before further experimental work.
- [ ] Complete every in-scope DELIVERY gate, including required runtime cases and actual host/model evaluation subsets.
- [ ] Preserve failed attempts, commands, exits, profiles, source/dependency/corpus/model hashes and unresolved findings.
- [ ] Establish production isolation and failure-domain-dependent backup/recovery evidence.
- [ ] Validate artifact sanitization with nonempty intended coverage. Missing inputs, zero coverage or an unverifiable result must block release.
- [ ] Establish data-preserving rollback compatibility and an operator recovery procedure.
- [ ] Freeze the release identity and obtain the independent G8 execution receipt under DELIVERY's review limits.
- [ ] Resolve every release blocker and obtain explicit authorization for release actions.

An unavailable, failed, skipped or unverified required scenario blocks release. There is no config-checked release exception. Operator acceptance of known gaps cannot substitute for the required evidence.

Running `src/p8/verify.py` does not itself create an independent reviewer. Its current exit 2 means INCOMPLETE. Even a future exit 0 cannot replace missing acceptance evidence or the required independent review.

## Recovery and rollback safety

Preserve accepted knowledge, the prior application and verified backups. Do not restore an older database over a live authority or use a working-file checkout as a data rollback.

Test downgrade/schema compatibility only when execution is authorized and in isolated fixtures. If old code cannot read the current schema, use maintenance/read-only operation and an explicit compatible migration.

Temporary restore regressions cover supported SQLite backup, archive validation, fresh epochs, retained historical citations and index bootstrap. They do not certify production scheduling, storage independence, RPO or RTO.

The proposed backup interval remains five minutes. Zero acknowledged-write-loss applies only to the surviving-authority failure domain. After total disk loss, recovery depends on a valid backup outside that failed disk.

Writes after that backup snapshot can be lost. Failed or delayed backups can increase the loss window beyond five minutes. If all backup copies share the failed disk, there may be no recoverable authority at all.

`src/authority/profile.yaml` retains the existing targets. Neither a configured interval nor fixture restore timings establish production recovery objectives. No commit, push, tag, merge, deployment or production restore is authorized here.


## 2026-11-13 authorized continuation (not a release)

The historical execution STOP above describes the earlier exhausted run. The
owner subsequently authorized direct autonomous implementation without Pi TUI.
That continuation does not relax any acceptance threshold or authorize a release.

Verified corrections now include transactional 100-slot unresolved admission,
metadata-only rejection, explicit caller-key forwarding, persisted terminal
publication/conflict receipts and idempotent decision replay. A real eight-process
shared-database test retains all proposals and produces one committed publication
and seven terminal conflicts. The invalid separate-in-memory-database test was
replaced. Sanitization now detects standalone questions/bodies, fails closed for
incomplete corpus inputs, and scans the declared runtime/root-file inventory.
That is not a clean-history or complete release-artifact certification.

The corrected core full suite passed 169 tests; Node lifecycle/protocol/integrity
tests passed 10; strict TypeScript checks passed. The separately reviewed worker
namespace experiment increased the full Python suite to 178 passing tests.
See `src/mcp/WORKER-BOUNDARY.md`: the experiment does not isolate existing direct-database
MCP adapters or establish a production/real-host boundary.

A fresh independent verifier was actually executed and rerun after corrections,
only in isolated copies. The final result is exit 2, INCOMPLETE, not G8 approval.
Its Git-file rollback test still does not prove preservation of accepted knowledge
across schema/application downgrade.

Recovered concurrent G2 evidence contains 100 completed queries with ten readers,
warm p95 4.154 seconds (FAIL against 2 seconds), and one visibility observation
of 20.138 seconds. The latter is not a tail-distribution certificate. That run's
RSS was not retained. Answer quality, independent representative holdout, durable
host-call journaling, full host subsets and production isolation remain open.

Exact correction hashes and passing/failing evidence are retained internally in
`.verification/2026-11-13-completion/`. Do not publish that raw evidence directory,
frozen evaluation inputs or the existing Git history as a release artifact.

### Trusted host journal continuation

Experimental opt-in journal is implemented and independently reviewed. It binds
trusted session/call identity to a deterministic scoped key and immutable payload;
checks live authority epoch and mutation-time epoch; fails closed after restore.
Real SIGKILL/restart, lost journal row, concurrent callers and backup/restore tests:
16 targeted journal/boundary tests passed independently. Complete isolated suite:
184 passed, one failed because the audit copy omitted root opencode.json; after
restoring that configuration only, the single failing test passed. This is not
a clean 185-test full-run receipt. Logs and hashes are retained under the journal
verification evidence. Actual Pi/Codex/other host durable identity integration
remains incomplete; no existing transport was switched to the experimental path.

Independent test-only continuation: seven real SQLite BUSY/FULL/publication-SIGKILL
fault tests passed (0.90s); combined journal/boundary/fault tests passed23 in the
implementer isolation. No physical disk exhaustion or real host integration claim.
Indexer-only embedding parallelism1 experiment preserved all250 corpus objects
but reduced indexer RSS only6.9% while slowing the cold build to17.455s. This
tuning was not promoted; no overlapping-workload or visibility-p95 claim.

### Bounded nonblocking authority reads

Selective async snapshot/resolve improvement promoted after independent192 Python
tests,17 Node tests,3 real-MCP model-free regressions and strict TypeScript checks.
One unchanged100-query/10-reader workload:1000 exact citations, warm p952.263s,
aggregateRSS2,616,967,168bytes. BOTH latency and2GiB gates still FAIL. No second
workload was run. Four bounded active RPC children can increase memory; this is
not a memory fix. Deadline includes queue/child and checks before/after JSON parse,
not preemption of parsing. Caller AbortSignal cancellation remains unintegrated.

### Separately held synthetic corpus correction

V1 lacks explicit split membership and is not an acceptable independent holdout.
Separate v2r1 fixture was independently reviewed after correcting authorization
scope, conflict visibility and redundant required gold. It has explicit family-
disjoint100dev/150heldout IDs,200positives/50controls,250authority-backed docs and
300exact authorized visible gold spans. Questions/gold stay outside coding/index
workspaces. This is synthetic regression data only, not a G0PASS: shared templates,
zero native-child eligibility and zero representative real-project coverage remain.
No holdout model evaluation or implementation tuning against individual cases ran.

Separate real-source-reading subset independently approved after two localized
ambiguity/span corrections:50answerable/10controls from10frozen source files,
24dev/36holdout,50exact UTF8spans, deterministic reproduction. Questions/gold
remain in private evaluator storage outside coding/index workspaces. File-disjoint
split does not imply semantic-fact independence across related modules. This is
single-project code-reading coverage, NOT representative all-project tasks, runtime
behavior or native-child evidence; G0 remains incomplete. No model evaluation ran.

Experimental pinnedQMD fork remains OUTSIDE installed wiki dependencies. Its
model-free lifecycle/capability review passed9tests after correcting a cache bypass.
One sequential native2document compatibility smoke passed:718,000,128B sampled
RSS, exact bodies/IDs, approved model digest, exit0; all4observed PIDs later absent.
This proves neither overlapping workload/G2 nor a single native-model allocation.
Offline enforcement was the existing JavaScript policy, not an OSnetwork sandbox.
Upstream native disposal is best-effort; resolvedclose is not cleanup proof.
Single-service integration remains isolated pending its own review and workload.

### Independent measurement audit and freshness semantics

Independent raw-artifact audit of the completed async-authority run confirms
100 unique calls, 1,000 exact citations, overall p95 2.848 seconds, warm p95
2.263 seconds and aggregate peak RSS 2,616,967,168 bytes. Coverage was
20 hybrid-current and 80 hybrid-stale responses. These are best-available
measurements during rebuild, NOT current-index-only performance evidence.
ARCHITECTURE's explicit best-available contract permits same-epoch older vector
generations plus current-snapshot lexical search. Newly published paraphrases
can be missed; neither completeness nor an absence claim follows. Strict
require-hybrid-current rejects lag with not-ready. The final visibility barrier
is assessed separately; one visibility observation is not a tail certificate.

The shared-owner service candidate passed isolated lifecycle/IPC tests and review,
but as of this status check its full native workload has NOT run. Preparation was
interrupted before runner creation. No completed shared-owner performance receipt
or release claim exists. The protected DELIVERY.md hash remains unchanged.

### Isolated shared-owner workload (not promoted)

The initial shared-service launch failed before any query: native binding probe
could not open ignored standard streams under the harness's read-only /dev.
A model-free reproduction isolated the cause. One explicitly authorized corrected
attempt used a private /dev namespace, preserving read-only host mounts and a
verified isolated network namespace. Both attempts and harness versions are kept.

Corrected run completed 100 requests across ten reader lanes, 1,000 exact citations
with no failures, exit zero and no surviving observed processes. Peak service plus
workers RSS was 1,057,169,408 bytes; conservative complete harness tree peaked at
1,148,776,448 bytes. Both are below 2 GiB. This is an isolated architecture result,
not deployment or proof of the number of native model instances.

Overall p95 was 2.437 seconds and warm p95 2.473 seconds: latency still FAILS
the unchanged 2-second target. Coverage was 20 current and 80 stale. Strict final
read returned the committed revision with snapshot=index sequence 251. One
wall-clock visibility observation was 25.158 seconds, not a visibility-tail proof.
Warm90 includes one strict request; the separately reported best-available89
subset is not identical to the previous warm90 baseline. The initial shared build
already loaded the model, so the raw legacy cold_first_wave label does NOT mean
cold-model startup. Topology and warm state differ from the old separate-process
run. No current-index-only latency acceptance is established.

Raw receipts, manifests, failed-attempt evidence and corrections are retained in
.verification/2026-11-13-completion/shared-owner-performance/. The experimental
fork/service remains outside installed production dependencies. Independent
artifact auditing and source-maintainability work continue; G2 and release remain
blocked. No further workload or promotion follows from this partial result.
