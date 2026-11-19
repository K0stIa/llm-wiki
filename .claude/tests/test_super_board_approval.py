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
PLAN = '{"human":["review"]}'


def comment(number, body, second, login="owner", edited=False):
    return {
        "id": number, "body": body, "user": {"login": login, "type": "User"},
        "created_at": f"2026-01-01T00:00:{second:02}Z",
        "updated_at": f"2026-01-01T00:00:{second + edited:02}Z",
    }


class ApprovalResume(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.config = self.path / "config.json"
        self.config.write_text(json.dumps({"project": {"owner": "example", "number": 1}}))
        self.env = dict(os.environ, PATH=f"{self.path}:{os.environ['PATH']}",
                        FIXTURES=str(self.path / "responses.json"),
                        SB_GITHUB_HALT_FILE=str(self.path / "halt"))
        gh = self.path / "gh"
        gh.write_text("""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
fixtures = json.load(open(os.environ["FIXTURES"]))
if a[:2] == ["pr", "list"]:
    key = "open"
elif a[:2] == ["api", "graphql"]:
    key = next((field for field in a if field.startswith("pr=")), "open")
    assert key != "open" or ("--paginate" in a and "--slurp" in a)
else:
    key = a[-1].split("?")[0]
print(json.dumps(fixtures[key]))
""")
        gh.chmod(0o755)
        self.args = ["python3", str(BIN / "super-board-approval.py"), "--repo", REPO]
        self.check = ["--pr", "42", "--head", HEAD, "--plan", PLAN]
        self.marker = self.run_command(self.args + self.check + ["--request"]).strip()
        pr = dict(headRefOid=HEAD, state="OPEN", headRefName="issue-7-approval",
                  isCrossRepository=False, headRepository={"nameWithOwner": REPO}, closingIssuesReferences={
                      "nodes": [], "pageInfo": {"hasNextPage": False}})
        self.pr = pr
        self.fixtures = {
            "open": [self.page([self.candidate(42, pr["headRefName"])])],
            "pr=42": [{"data": {"repository": {"pullRequest": pr}}}],
            f"repos/{REPO}/issues/7/comments": [[]],
            f"repos/{REPO}/issues/42/comments": [[comment(1, self.marker, 1), comment(2, "done", 3)]],
            f"repos/{REPO}/collaborators/owner/permission": {"permission": "admin"},
            f"repos/{REPO}/collaborators/guest/permission": {"permission": "read"},
        }

    @staticmethod
    def candidate(number, branch, repository=REPO):
        return {"number": number, "headRefName": branch,
                "headRepository": {"nameWithOwner": repository}}

    @staticmethod
    def page(nodes, cursor=None):
        return {"data": {"repository": {"pullRequests": {
            "nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
        }}}}

    def run_command(self, args, input=None):
        return subprocess.run(args, input=input, text=True, capture_output=True,
                              cwd=ROOT, env=self.env, check=True).stdout

    def save(self):
        (self.path / "responses.json").write_text(json.dumps(self.fixtures))

    def wave(self):
        self.save()
        entry = {"number": 7, "title": "Approval", "needsYou": True, "runnable": False}
        deps = self.run_command(self.args + ["--deps"], json.dumps({"7": entry}))
        self.evidence = json.loads(deps)["7"]
        (self.path / "deps.json").write_text(deps)
        card = {"number": 7, "title": "Approval", "type": "Issue"}
        items = {"items": [{"status": "Blocked", "title": "Approval", "content": card}]}
        (self.path / "items.json").write_text(json.dumps(items))
        return json.loads(self.run_command(["bash", str(BIN / "super-board-wave-plan.sh"),
                                            "--config", str(self.config),
                                            "--items", str(self.path / "items.json"),
                                            "--deps", str(self.path / "deps.json")]))

    def test_pr_side_resumes_correct_card_and_standalone_still_works(self):
        self.assertEqual([card["number"] for card in self.wave()["resume"]], [7])
        self.assertTrue(json.loads(self.run_command(self.args + self.check))["approved"])
        wrong_scope = self.check[:-1] + ["{}"]
        self.assertFalse(json.loads(self.run_command(self.args + wrong_scope))["approved"])

    def test_unrelated_or_fork_pr_does_not_resume(self):
        for branch, fork in [("issue-70-other", False), ("issue-7-approval", True)]:
            with self.subTest(branch=branch, fork=fork):
                self.pr.update(headRefName=branch, isCrossRepository=fork)
                self.fixtures["open"] = [self.page([self.candidate(42, branch)])]
                self.assertEqual(self.wave()["resume"], [])

    def test_reply_cannot_move_between_prs(self):
        self.fixtures["open"] = [self.page([self.candidate(42, "issue-7-approval"),
                                            self.candidate(43, "issue-8-approval")])]
        reply = self.fixtures[f"repos/{REPO}/issues/42/comments"][0].pop()
        self.fixtures[f"repos/{REPO}/issues/43/comments"] = [[reply]]
        self.assertEqual(self.wave()["resume"], [])

    def test_ambiguous_workflow_branches_stay_blocked(self):
        self.fixtures["open"] = [self.page([self.candidate(42, "issue-7-approval")], "next"),
                                 self.page([self.candidate(43, "issue-7-other")])]
        self.assertEqual(self.wave()["resume"], [])

    def test_stale_edited_or_untrusted_approval_does_not_resume(self):
        for marker, edited, signer in [(self.marker.replace(HEAD, "b" * 40), False, "owner"),
                                       (self.marker, True, "owner"),
                                       (self.marker, False, "guest")]:
            with self.subTest(edited=edited, signer=signer):
                self.fixtures[f"repos/{REPO}/issues/42/comments"] = [[
                    comment(1, marker, 1, edited=edited), comment(2, "done", 3, signer)]]
                wave = self.wave()
                self.assertEqual(wave["resume"], [])
                self.assertEqual(wave["refreshApproval"], [])

    def test_live_selected_pr_requires_same_origin_metadata(self):
        self.pr["headRepository"] = None
        self.assertEqual(self.wave()["resume"], [])

    def test_ambiguous_issue_requests_never_select_a_pr(self):
        self.fixtures[f"repos/{REPO}/issues/7/comments"] = [[
            comment(3, self.marker, 0), comment(4, self.marker.replace(HEAD, "b" * 40), 0)]]
        wave = self.wave()
        self.assertEqual(wave["resume"], [])
        self.assertEqual(wave["refreshApproval"], [])
        self.assertEqual(self.evidence["approvalWhy"], "ambiguous newest human request")

    def test_stale_issue_pin_requires_refresh_even_after_pr_approval(self):
        self.pr["closingIssuesReferences"]["nodes"] = [
            {"number": 7, "repository": {"nameWithOwner": REPO}}]
        self.fixtures[f"repos/{REPO}/issues/7/comments"] = [[
            comment(3, self.marker.replace(HEAD, "b" * 40), 0)]]
        wave = self.wave()
        self.assertEqual(wave["resume"], [])
        self.assertEqual([card["number"] for card in wave["refreshApproval"]], [7])

    def test_same_repository_candidate_survives_fork_and_invalid_repository(self):
        self.fixtures["open"] = [self.page([
            self.candidate(42, "issue-7-approval"),
            self.candidate(43, "issue-7-approval", "fork/wiki"),
            self.candidate(44, "issue-7-approval", None),
        ])]
        self.assertEqual([card["number"] for card in self.wave()["resume"]], [7])

    def test_sole_candidate_on_later_page(self):
        first = [self.candidate(n, "unrelated") for n in range(100, 200)]
        self.fixtures["open"] = [self.page(first, "next"),
                                 self.page([self.candidate(42, "issue-7-approval")])]
        self.assertEqual([card["number"] for card in self.wave()["resume"]], [7])

    def test_incomplete_candidate_pages_hold(self):
        first = self.page([self.candidate(42, "issue-7-approval")], "next")
        for pages in ([first], [first, self.page(None)]):
            with self.subTest(pages=pages):
                self.fixtures["open"] = pages
                self.assertEqual(self.wave()["resume"], [])
                self.assertEqual(self.evidence["approvalWhy"], "approval evidence could not be verified")

    def test_unlinked_issue_handoff_and_independent_human_blocker(self):
        url = "https://github.com/Example/Wiki/pull/42#issuecomment-1"
        body = ("[reviewer] [blocker] 🙋 Your turn on #7 — Approval\n\n"
                "Review PR #42 and post a new PR comment containing only `done`. "
                f"[Pinned approval request]({url})\n\n"
                "<details><summary>Why, and what I checked</summary>\n\n"
                "Reason tag: 🙋 needs you · Owner: repository maintainer\nblocked-by: -\n</details>")
        issues = self.fixtures[f"repos/{REPO}/issues/7/comments"][0]
        for pointer, resume in [(comment(3, body, 2), [7]),
                                (comment(3, body, 2, edited=True), []),
                                (comment(3, body.replace("comment-1", "comment-2"), 2), []),
                                (comment(3, body.replace("/pull/", "/issues/"), 2), [])]:
            issues[:] = [pointer]
            self.assertEqual([card["number"] for card in self.wave()["resume"]], resume)
        issues[:] = [comment(3, body, 2), comment(4, "Reason tag: 🙋\nResolve rollout.", 5)]
        self.assertEqual(self.wave()["resume"], [])

    def test_fallback_rejects_existing_links(self):
        links = self.pr["closingIssuesReferences"]
        self.fixtures[f"repos/{REPO}/issues/42/comments"] = [[]]
        self.fixtures[f"repos/{REPO}/issues/8/comments"] = [[
            comment(1, self.marker, 1), comment(2, "done", 3)]]
        links["nodes"] = [{"number": n, "repository": {"nameWithOwner": REPO}} for n in (7, 8)]
        self.assertEqual(self.wave()["resume"], [])
        links["nodes"] = [{"number": 7, "repository": {"nameWithOwner": "other/wiki"}}]
        self.fixtures[f"repos/{REPO}/issues/42/comments"] = self.fixtures[f"repos/{REPO}/issues/8/comments"]
        self.assertEqual(self.wave()["resume"], [])

    def test_offline_dependencies_do_not_read_github(self):
        deps = self.run_command(self.args[:-1] + ["", "--deps"],
                                json.dumps({"7": {"number": 7, "needsYou": True}}))
        self.assertFalse(json.loads(deps)["7"]["needsYouDone"])

    def test_linked_issue_can_still_hold_the_request_and_reply(self):
        self.pr["closingIssuesReferences"]["nodes"] = [
            {"number": 7, "repository": {"nameWithOwner": REPO}}]
        self.fixtures[f"repos/{REPO}/issues/7/comments"] = self.fixtures.pop(
            f"repos/{REPO}/issues/42/comments")
        self.fixtures[f"repos/{REPO}/issues/42/comments"] = [[]]
        self.fixtures["open"] = []
        self.assertEqual([card["number"] for card in self.wave()["resume"]], [7])
        self.pr.update(isCrossRepository=True, headRepository={"nameWithOwner": "fork/wiki"})
        self.assertEqual([card["number"] for card in self.wave()["resume"]], [7])
        self.assertTrue(json.loads(self.run_command(self.args + self.check))["approved"])
        self.pr["headRefOid"] = "b" * 40
        wave = self.wave()
        self.assertEqual(wave["resume"], [])
        self.assertEqual([card["number"] for card in wave["refreshApproval"]], [7])



if __name__ == "__main__":
    unittest.main()
