"""Synthetic GitHub responses for approval-driven board resume."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / ".claude/bin"
REPO = "example/wiki"
HEAD = "a" * 40
HANDOFF = ("Reason tag: 🙋 needs you\napproval-handoff: "
           "https://github.com/example/wiki/pull/42#issuecomment-1\nblocked-by: -")
ISSUE_COMMENTS = f"repos/{REPO}/issues/7/comments"
PR_COMMENTS = f"repos/{REPO}/issues/42/comments"
PLAN = '{"human":["review"]}'


def comment(number, body, second, login="owner", edited=False):
    return {
        "id": number, "body": body, "user": {"login": login, "type": "User"},
        "created_at": f"2026-01-01T00:00:{second:02}Z",
        "updated_at": f"2026-01-01T00:00:{second + edited:02}Z",
    }


class ApprovalResume(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.path / "config.json").write_text('{"project":{"owner":"example","number":1}}')
        self.env = dict(os.environ, PATH=f"{self.path}:{os.environ['PATH']}",
                        FIXTURES=str(self.path / "responses.json"),
                        SB_GITHUB_HALT_FILE=str(self.path / "halt"))
        gh = self.path / "gh"
        gh.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
fixture_file = Path(os.environ["FIXTURES"])
fixtures = json.loads(fixture_file.read_text())
if a[:2] == ["api", "graphql"]:
    key = next((field for field in a if field.startswith("pr=")), "open")
    assert "--paginate" in a and "--slurp" in a
    if any("issues(states:OPEN" in arg for arg in a):
        key = "issues"
    if key == "pr=42" and "fresh_issue_comments" in fixtures:
        fixtures["repos/example/wiki/issues/7/comments"] = fixtures["fresh_issue_comments"]
        fixture_file.write_text(json.dumps(fixtures))
else:
    key = a[-1].split("?")[0]
print(json.dumps(fixtures[key]))
""")
        gh.chmod(0o755)
        self.check = [str(BIN / "super-board-approval.py"), "--repo", REPO, "--pr", "42",
                      "--head", HEAD, "--plan", PLAN]
        self.marker = self.run_command(self.check + ["--request"]).strip()
        self.issue_request = f"Reason tag: 🙋 needs you\n{self.marker}\nblocked-by: -"
        pr = dict(headRefOid=HEAD, state="OPEN", headRefName="issue-7-approval",
                  isCrossRepository=False, headRepository={"nameWithOwner": REPO}, closingIssuesReferences={
                      "nodes": [], "pageInfo": {"hasNextPage": False}})
        self.pr = pr
        self.fixtures = {
            "open": [self.page([self.candidate(42, pr["headRefName"])])],
            "pr=42": [{"data": {"repository": {"pullRequest": pr}}}],
            ISSUE_COMMENTS: [[comment(3, HANDOFF, 2)]],
            PR_COMMENTS: [[comment(1, self.marker, 1), comment(2, "done", 3)]],
            f"repos/{REPO}/collaborators/owner/permission": {"permission": "admin"},
            f"repos/{REPO}/collaborators/guest/permission": {"permission": "read"},
        }

    def link_issues(self, *numbers, repository=REPO):
        self.pr["closingIssuesReferences"]["nodes"] = [
            {"number": n, "repository": {"nameWithOwner": repository}} for n in numbers]

    @staticmethod
    def candidate(number, branch, repository=REPO):
        return {"number": number, "headRefName": branch,
                "headRepository": {"nameWithOwner": repository}}

    @staticmethod
    def page(nodes, cursor=None):
        return {"data": {"repository": {"pullRequests": {
            "nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
        }}}}

    def run_command(self, args):
        return subprocess.run(args, text=True, capture_output=True,
                              cwd=ROOT, env=self.env, check=True).stdout

    def wave(self, labels=()):
        issue = dict(number=7, title="Approval", state="OPEN", body="## Blocked by\n- None.",
                     labels={"nodes": [{"name": name} for name in labels]},
                     comments={"nodes": sum(self.fixtures[ISSUE_COMMENTS], [])})
        self.fixtures["issues"] = [{"data": {"repository": {"issues": {
            "nodes": [issue], "pageInfo": {"hasNextPage": False},
        }}}}]
        (self.path / "responses.json").write_text(json.dumps(self.fixtures))
        deps = self.run_command(["bash", str(BIN / "super-board-deps.sh"), "--repo", REPO])
        self.evidence = json.loads(deps)["7"]
        (self.path / "deps.json").write_text(deps)
        item = {"status": "Blocked", "title": "Approval", "labels": list(labels),
                "content": {"number": 7, "type": "Issue"}}
        (self.path / "items.json").write_text(json.dumps({"items": [item]}))
        return json.loads(self.run_command([
            "bash", str(BIN / "super-board-wave-plan.sh"), "--config", str(self.path / "config.json"),
            "--items", str(self.path / "items.json"), "--deps", str(self.path / "deps.json"),
        ]))

    def test_pr_side_resumes_correct_card_and_standalone_still_works(self):
        self.assert_resumed()
        self.assertTrue(json.loads(self.run_command(self.check))["approved"])
        self.assertFalse(json.loads(self.run_command(self.check[:-1] + ["{}"]))["approved"])

    def test_unrelated_or_fork_pr_does_not_resume(self):
        for key, invalid in (("headRefName", "issue-70-other"), ("isCrossRepository", True), ("headRepository", None)):
            with self.subTest(field=key):
                original = self.pr[key]
                self.pr[key] = invalid
                self.assert_held()
                self.pr[key] = original

    def test_reply_cannot_move_between_prs(self):
        self.fixtures["open"][0]["data"]["repository"]["pullRequests"]["nodes"].append(
            self.candidate(43, "issue-8-approval"))
        self.fixtures[f"repos/{REPO}/issues/43/comments"] = [[self.fixtures[PR_COMMENTS][0].pop()]]
        self.assert_held()

    def test_stale_edited_or_untrusted_approval_does_not_resume(self):
        for marker, edited, signer in [(self.marker.replace(HEAD, "b" * 40), False, "owner"),
                                       (self.marker, True, "owner"),
                                       (self.marker, False, "guest")]:
            with self.subTest(edited=edited, signer=signer):
                self.fixtures[PR_COMMENTS] = [[
                    comment(1, marker, 1, edited=edited), comment(2, "done", 3, signer)]]
                self.assert_held()
                self.assertFalse(self.evidence["approvalRefresh"])

    def test_ambiguous_issue_requests_never_select_a_pr(self):
        self.fixtures[ISSUE_COMMENTS] = [[
            comment(3, self.issue_request, 0), comment(4, self.issue_request.replace(HEAD, "b" * 40), 0)]]
        self.assert_held()
        self.assertFalse(self.evidence["approvalRefresh"])
        self.assertEqual(self.evidence["approvalWhy"], "ambiguous newest human request")

    def test_stale_issue_pin_requires_refresh_even_after_pr_approval(self):
        self.link_issues(7)
        self.fixtures[ISSUE_COMMENTS] = [[comment(3, self.issue_request.replace(HEAD, "b" * 40), 0)]]
        self.assert_held()
        self.assertTrue(self.evidence["approvalRefresh"])

    def test_workflow_candidate_pagination(self):
        candidate = self.candidate(42, "issue-7-approval")
        first = self.page([self.candidate(44, "issue-7-approval", None),
                           self.candidate(43, "issue-7-approval", "fork/wiki")], "next")
        self.fixtures["open"] = [first, self.page([candidate])]
        self.assert_resumed()
        first = self.page([candidate], "next")
        for rest in ([], [self.page(None)], [self.page([self.candidate(43, "issue-7-other")])]):
            self.fixtures["open"] = [first, *rest]
            self.assert_held()

    def test_unlinked_handoff_requires_exact_unedited_pointer(self):
        for body in ("Thanks.", HANDOFF.replace("/pull/", "/issues/"), HANDOFF + "\nVerify rollout.", HANDOFF.rsplit("\n", 1)[0]):
            self.fixtures[ISSUE_COMMENTS] = [[comment(3, body, 2)]]
            self.assertEqual(self.wave()["resume"], [])
        for comments in ([], [comment(3, HANDOFF, 2, edited=True)]):
            self.fixtures[ISSUE_COMMENTS] = [comments]
            self.assertEqual(self.wave()["resume"], [])
        self.assertTrue(json.loads(self.run_command(self.check))["approved"])

    def test_sweep_and_resume_use_distinct_evidence(self):
        reply = self.fixtures[PR_COMMENTS][0].pop()
        self.assert_held()
        self.fixtures[PR_COMMENTS][0].append(reply)
        self.assert_resumed()
        dependency = comment(3, "blocked-by: 99", 2)
        for extra, labels in (([], ()), ([comment(4, "approval-handoff: invalid", 3, "guest")], ()),
                              ([], ("needs-you",))):
            self.fixtures[ISSUE_COMMENTS] = [[dependency, *extra]]
            wave = self.wave(labels)
            self.assertEqual(wave["resume"], [])
            self.assertEqual([(c["number"], c["clearedBy"]) for c in wave["sweep"]], [(7, [99])])

    def assert_resumed(self):
        wave = self.wave()
        self.assertEqual(([card["number"] for card in wave["resume"]], wave["sweep"]), ([7], []))

    def assert_held(self):
        wave = self.wave()
        self.assertEqual((wave["sweep"], wave["resume"]), ([], []))

    def test_refreshed_request_requires_new_reply_and_handoff(self):
        old = comment(3, HANDOFF, 2)
        new = comment(5, HANDOFF.replace("comment-1", "comment-4"), 5)
        self.fixtures[PR_COMMENTS][0][0]["body"] = self.marker.replace(HEAD, "b" * 40)
        self.fixtures[PR_COMMENTS][0].append(comment(4, self.marker, 4))
        self.fixtures[ISSUE_COMMENTS] = [[old, new]]
        self.assert_held()
        self.fixtures[PR_COMMENTS][0].append(comment(6, "done", 6))
        self.assert_resumed()
        for blockers in ([old], [old, new, comment(8, "[reviewer] [blocker] Check rollout.", 7)],
                         [dict(old, updated_at=new["created_at"]), new],
                         [dict(old, body=HANDOFF.replace("comment-1", "comment-99")), new]):
            self.fixtures[ISSUE_COMMENTS] = [blockers]
            self.assert_held()

    def test_fallback_rejects_existing_links(self):
        for repo in (REPO, "other/wiki"):
            self.link_issues(7, repository=repo)
            self.assert_held()

    def test_linked_card_request_can_be_superseded_on_another_linked_issue(self):
        self.link_issues(7, 8)
        self.fixtures[ISSUE_COMMENTS] = [[comment(3, self.issue_request, 0), comment(4, "done", 1)]]
        self.fixtures[PR_COMMENTS] = [[]]
        latest = [comment(5, self.marker, 2)]
        self.fixtures[f"repos/{REPO}/issues/8/comments"] = [latest]
        self.assertEqual(self.wave()["resume"], [])
        latest.append(comment(6, "done", 3))
        self.assert_resumed()

    def test_linked_edited_issue_request_requires_supersession(self):
        self.link_issues(7)
        routing_request = comment(3, self.issue_request, 0, edited=True)
        self.fixtures[ISSUE_COMMENTS] = [[routing_request, comment(4, "done", 3)]]
        pr_comments = self.fixtures[PR_COMMENTS]
        self.fixtures[PR_COMMENTS] = [[]]
        self.assert_held()
        self.assertIn("request was edited", self.evidence["approvalWhy"])
        self.fixtures[PR_COMMENTS] = pr_comments
        self.assert_resumed()

    def test_linked_issue_can_still_hold_the_request_and_reply(self):
        self.link_issues(7)
        self.fixtures[ISSUE_COMMENTS] = [[comment(1, self.issue_request, 1), comment(2, "done", 3)]]
        self.fixtures[PR_COMMENTS] = [[]]
        self.assert_resumed()
        self.fixtures["fresh_issue_comments"] = [[
            *self.fixtures[ISSUE_COMMENTS][0], comment(4, "Reason tag: 🙋 needs you", 4)]]
        self.assertEqual(self.wave()["resume"], [], "A blocker posted after metadata supersedes the reply")
        self.assertIn("latest request does not cover", self.evidence["approvalWhy"])
        del self.fixtures["fresh_issue_comments"]
        self.pr.update(isCrossRepository=True, headRepository={"nameWithOwner": "fork/wiki"})
        self.assert_resumed()
        self.assertTrue(json.loads(self.run_command(self.check))["approved"])
        self.pr["headRefOid"] = "b" * 40
        self.assert_held()
        self.assertTrue(self.evidence["approvalRefresh"])
