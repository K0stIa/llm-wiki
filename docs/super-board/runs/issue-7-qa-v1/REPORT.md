# Issue #7 QA v1

Tested draft PR #11 at OpenHands-reviewed head `a4cf372f01aa5be7e50e149b6984272f5370ff00` against `super-board/implementation`. All approval and planner execution used deterministic GitHub fixtures. The base checkout supplied live GitHub reads and write guards.

| Acceptance criterion | Observable evidence |
|---|---|
| Resume the correct card from a current PR-side approval | `test_pr_side_resumes_correct_card_and_standalone_still_works` selects card 7. `test_sweep_and_resume_use_distinct_evidence` runs the dependency script and wave planner before and after approval. The card stays held before approval and appears only in resume after approval. A cleared ordinary dependency appears only in sweep, including with a guest marker or stale display label. |
| Hold unrelated, stale, edited or untrusted approvals | `test_unrelated_or_fork_pr_does_not_resume`, `test_reply_cannot_move_between_prs` and `test_stale_edited_or_untrusted_approval_does_not_resume` assert empty resume and sweep lists. `test_unlinked_handoff_requires_exact_unedited_pointer` and `test_refreshed_request_requires_new_reply_and_handoff` cover missing, edited and refreshed pointers, stale replies and independent blockers. An independent fixture probe supplied a PR body with `Closes #7` and then an exact guest-authored handoff. Each left resume empty. A trusted handoff resumed card 7 on the non-default base. |
| Preserve linked and standalone approval | The linked issue fixtures cover issue-side requests, superseding blockers and stale heads. The standalone fixture passes with matching scope and rejects a different scope. An independent probe changed the live fixture head after approval and confirmed that the planner holds the card and the merge-side helper reports a head change. The base merge gate calls the approval helper with the current head and merge-policy plan and retains the merge decision. |

The OpenHands closing-link case reproduced in an independent fixture probe. Adding a link after a PR-side approval puts the card on hold. A fresh issue-side request and reply restore resume. This matches the disposition for the linked approval route.

The ledger uses integration assertions on the real scripts with synthetic GitHub responses. Component and browser tests are inapplicable to this CLI flow. The trust probes exercised the output of the actual planner and helper. Dropping the trusted handoff requirement would admit the guest or body-only cases. Dropping the merge-side head or scope comparison would accept the corresponding mismatch probes.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s .claude/tests -v` passed all 13 board fixtures.
- Three independent probes passed. They reused the board fixture harness for the trust boundary, head and scope checks, and closing-link transition.
- `node_modules/.bin/tsc -p tsconfig.json` passed.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -m 'not tier_b and not tier_c' tests/hypothesis/test_g2_measurement.py tests/hypothesis/test_eval_v2_scoring.py tests/hypothesis/test_eval_v2_replay.py -k 'not test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint'` passed 60 tests and deselected the private-corpus case.
- `node --import tsx --test tests/runtime/native-search-queue.test.mjs tests/runtime/trace-v2.test.mjs` passed all 14 tests.

Python and Node manifests and locks matched the isolated base. Verification reused its installed dependencies. Screenshots are inapplicable to these CLI acceptance criteria. Real G2 runs and receipt publication were outside the verification scope.
