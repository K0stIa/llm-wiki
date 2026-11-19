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
    key = next(field for field in a if field.startswith("pr="))
else:
    key = a[-1].split("?")[0]
print(json.dumps(fixtures[key]))
""")
        gh.chmod(0o755)
        self.args = ["python3", str(BIN / "super-board-approval.py"), "--repo", REPO]
        self.check = ["--pr", "42", "--head", HEAD, "--plan", PLAN]
        self.marker = self.run_command(self.args + self.check + ["--request"]).strip()
        pr = dict(headRefOid=HEAD, state="OPEN", headRefName="issue-7-approval",
                  isCrossRepository=False, closingIssuesReferences={
                      "nodes": [], "pageInfo": {"hasNextPage": False}})
        self.pr = pr
        self.fixtures = {
            "open": [dict(number=42, title="Approval", body="", url="https://github.com/example/wiki/pull/42",
                          headRefName=pr["headRefName"], headRefOid=HEAD, files=[],
                          baseRefName="implementation", isDraft=False)],
            "pr=42": [{"data": {"repository": {"pullRequest": pr}}}],
            f"repos/{REPO}/issues/7/comments": [[]],
            f"repos/{REPO}/issues/42/comments": [[comment(1, self.marker, 1), comment(2, "done", 3)]],
            f"repos/{REPO}/collaborators/owner/permission": {"permission": "admin"},
            f"repos/{REPO}/collaborators/guest/permission": {"permission": "read"},
        }

    def run_command(self, args, input=None):
        return subprocess.run(args, input=input, text=True, capture_output=True,
                              cwd=ROOT, env=self.env, check=True).stdout

    def save(self):
        (self.path / "responses.json").write_text(json.dumps(self.fixtures))

    def wave(self):
        self.save()
        entry = {"number": 7, "title": "Approval", "needsYou": True, "runnable": False}
        deps = self.run_command(self.args + ["--deps"], json.dumps({"7": entry}))
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
                self.fixtures["open"][0]["headRefName"] = branch
                self.assertEqual(self.wave()["resume"], [])

    def test_reply_cannot_move_between_prs(self):
        other = dict(self.fixtures["open"][0], number=43, headRefName="issue-8-approval")
        self.fixtures["open"].append(other)
        reply = self.fixtures[f"repos/{REPO}/issues/42/comments"][0].pop()
        self.fixtures[f"repos/{REPO}/issues/43/comments"] = [[reply]]
        self.assertEqual(self.wave()["resume"], [])

    def test_ambiguous_workflow_branches_stay_blocked(self):
        other = dict(self.fixtures["open"][0], number=43, headRefName="issue-7-other")
        self.fixtures["open"].append(other)
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
        self.assertTrue(json.loads(self.run_command(self.args + self.check))["approved"])


if __name__ == "__main__":
    unittest.main()
