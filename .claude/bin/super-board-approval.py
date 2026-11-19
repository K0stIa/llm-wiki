#!/usr/bin/env python3
"""Read-only, head-bound human approval shared by the planner and merge gate.

A trusted request pins the code and human steps BEFORE a human replies `done`.
Labels only describe UI state. They never authorize a merge. No GitHub writes.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re
import subprocess
import sys

_reader_spec = importlib.util.spec_from_file_location("github_read", Path(__file__).with_name("super-board-github-read.py"))
github_read = importlib.util.module_from_spec(_reader_spec)
_reader_spec.loader.exec_module(github_read)

PREFIX = "approval-request: "
SHA = re.compile(r"[0-9a-f]{40}\Z")
SCOPE = re.compile(r"[0-9a-f]{64}\Z")
BLOCK = re.compile(r"Reason tag:[^\n]*🙋|^[ \t]*approval-handoff:|^approval-request:", re.M)
DONE = re.compile(r"\s*done[.!]?\s*\Z", re.I)


def scope_for(plan):
    # Exclude UI-only `done`; a label change must not change what was approved.
    relevant = {key: plan.get(key, []) for key in ("human", "migrations", "run", "needs_you")}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request_for(repo, pr, head, scope):
    return {"repo": repo.lower(), "pr": int(pr), "head": head, "scope": scope}


def marker(request):
    return PREFIX + json.dumps(request, sort_keys=True, separators=(",", ":"))


def parse_request(comment):
    lines = [line for line in (comment.get("body") or "").splitlines() if line.startswith(PREFIX)]
    if len(lines) != 1:
        return None
    try:
        value = json.loads(lines[0][len(PREFIX):])
        if (not isinstance(value, dict) or not isinstance(value.get("repo"), str)
                or not re.fullmatch(r"[^/\s]+/[^/\s]+", value["repo"])
                or type(value.get("pr")) is not int or value["pr"] < 1
                or not SHA.fullmatch(value.get("head", ""))
                or not SCOPE.fullmatch(value.get("scope", ""))):
            return None
        return value
    except (ValueError, TypeError):
        return None


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing comment timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("comment timestamp lacks timezone")
    return result


def trusted_blocks(comments, permission, *, unlinked_issue=None):
    result = []
    for block in comments:
        body = block.get("body") or ""
        issue_block = (unlinked_issue is not None and block.get("source") == unlinked_issue
                       and re.search(r"Reason tag:|^\[\w+\] \[blocker\]", body, re.M))
        if not (issue_block or BLOCK.search(body)):
            continue
        user = block.get("user") or {}
        if not user.get("login") or user.get("type") not in ("User", "Bot"):
            raise ValueError("requester identity could not be verified")
        if permission(user["login"]) in ("write", "maintain", "admin"):
            result.append(block)
    return result


def is_pr_handoff(block, issue, request, expected):
    repo = re.escape(expected["repo"])
    url = rf"https://github\.com/(?i:{repo})/pull/{expected['pr']}#issuecomment-{request['id']}"
    return (
        block["source"] == issue
        and re.fullmatch(rf"Reason tag: 🙋 needs you\napproval-handoff: {url}", block["body"]) is not None
        and timestamp(block["updated_at"]) == timestamp(block["created_at"])
        and timestamp(block["created_at"]) > timestamp(request["created_at"])
    )


def validate(comments, expected, permission, *, unlinked_issue=None):
    """Pure verdict; permission(login) is a current repository permission lookup."""
    def hold(why):
        return {"approved": False, "why": why}

    if not SHA.fullmatch(expected.get("head", "")):
        return hold("current PR head is unavailable")
    try:
        blocks = trusted_blocks(comments, permission, unlinked_issue=unlinked_issue)
        if unlinked_issue is not None:
            issue_blocks = [c for c in blocks if c["source"] != expected["pr"]]
            blocks = [c for c in blocks if c["source"] == expected["pr"]]
        if not blocks:
            return hold("no request from a trusted repository collaborator")
        # Any later human block supersedes the old request, including one with
        # missing/malformed metadata. Equal-second requests are ambiguous: hold.
        latest_time = max(timestamp(c.get("created_at")) for c in blocks)
        latest = [c for c in blocks if timestamp(c.get("created_at")) == latest_time]
        if len(latest) != 1:
            return hold("ambiguous newest human request")
        request_comment = latest[0]
        if unlinked_issue is not None and not (issue_blocks and all(
            is_pr_handoff(c, unlinked_issue, request_comment, expected) for c in issue_blocks
        )):
            return hold("issue has a human block beyond the canonical PR handoff")
        request = parse_request(request_comment)
        if request is None or any(request.get(k) != v for k, v in expected.items() if k != "head"):
            return hold("the latest request does not cover the current code and human steps")
        if timestamp(request_comment.get("updated_at")) != latest_time:
            return hold("approval request was edited; post a fresh request")
        requester = request_comment.get("user") or {}
        if not requester.get("login") or permission(requester["login"]) not in ("write", "maintain", "admin"):
            return hold("requester authority could not be verified")
        if not isinstance(request_comment.get("source"), int) or not request_comment.get("id"):
            return hold("request identity is missing")
        if request["head"] != expected["head"]:
            return dict(hold("PR head changed after review"), headChanged=True)
        for comment in comments:
            if (not comment.get("id") or not DONE.fullmatch(comment.get("body") or "")
                    or comment.get("source") != request_comment.get("source")):
                continue
            created = timestamp(comment.get("created_at"))
            if created <= latest_time or timestamp(comment.get("updated_at")) != created:
                continue
            author = comment.get("user") or {}
            if (author.get("type") == "User" and author.get("login")
                    and permission(author["login"]) in ("write", "maintain", "admin")):
                return {"approved": True, "why": "trusted human confirmed the current request",
                        "request": request, "requestId": request_comment.get("id"),
                        "approvalId": comment.get("id"), "approver": author["login"]}
        return hold("waiting for a trusted human to comment done on the current request")
    except (ValueError, TypeError, KeyError):
        return hold("approval evidence is incomplete or unreadable")


class GitHub:
    def __init__(self, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("missing or invalid repository")
        self.repo = repo.lower()
        self.permissions = {}

    @staticmethod
    def read(*args):
        kind = ("approval" if "graphql" in args else "comments" if "--paginate" in args
                else "permission" if args[-1].endswith("/permission") else "json")
        return github_read.read(list(args), kind)[1]

    def permission(self, login):
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\[bot\])?", login):
            return None
        if login not in self.permissions:
            value = self.read("api", f"repos/{self.repo}/collaborators/{login}/permission")
            self.permissions[login] = value.get("permission")
        return self.permissions[login]

    def comments(self, number):
        pages = self.read("api", "--paginate", "--slurp",
                          f"repos/{self.repo}/issues/{number}/comments?per_page=100")
        if not isinstance(pages, list) or not pages or any(not isinstance(p, list) for p in pages):
            raise ValueError("unreadable comments")
        if any(not isinstance(c, dict) for page in pages for c in page):
            raise ValueError("unreadable comment")
        return [dict(comment, source=number) for page in pages for comment in page]

    def same_origin(self, pr):
        repository = pr.get("headRepository")
        origin = repository.get("nameWithOwner") if isinstance(repository, dict) else None
        return isinstance(origin, str) and origin.lower() == self.repo

    def open_prs(self):
        query = """query($owner:String!,$repo:String!,$endCursor:String){
          repository(owner:$owner,name:$repo){
            pullRequests(states:OPEN,first:100,after:$endCursor){
              pageInfo{hasNextPage endCursor} nodes{number headRefName headRepository{nameWithOwner}}
            }}}"""
        owner, name = self.repo.split("/")
        _, pages = github_read.read(
            ["api", "graphql", "--paginate", "--slurp", "-f", f"query={query}",
             "-F", f"owner={owner}", "-F", f"repo={name}"], "array")
        if not pages:
            raise ValueError("missing open PR pages")
        branches, cursors = {}, set()
        for index, page in enumerate(pages):
            prs = page["data"]["repository"]["pullRequests"]
            info, nodes = prs["pageInfo"], prs["nodes"]
            more = index + 1 < len(pages)
            if info["hasNextPage"] is not more or not isinstance(nodes, list):
                raise ValueError("incomplete open PR pages")
            if more:
                cursor = info["endCursor"]
                if not isinstance(cursor, str) or not cursor or cursor in cursors or not nodes:
                    raise ValueError("invalid open PR cursor")
                cursors.add(cursor)
            for pr in nodes:
                number, branch = pr["number"], pr["headRefName"]
                if type(number) is not int or number < 1 or number in branches or not isinstance(branch, str) or not branch:
                    raise ValueError("invalid open PR identity")
                branches[number] = branch if self.same_origin(pr) else None
        return {number: branch for number, branch in branches.items() if branch}

    def pr(self, number):
        # Paginate linked issues too: an omitted newer request must never make
        # an older approval authoritative. Remote links rule out the unlinked
        # fallback, while approvals only read comments from this repository.
        query = '''query($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
          repository(owner:$owner,name:$repo){pullRequest(number:$pr){headRefOid state headRefName isCrossRepository headRepository{nameWithOwner}
            closingIssuesReferences(first:100,after:$endCursor){
              pageInfo{hasNextPage endCursor} nodes{number repository{nameWithOwner}}
            }}}}'''
        owner, name = self.repo.split("/")
        pages = self.read("api", "graphql", "--paginate", "--slurp", "-f", f"query={query}",
                          "-F", f"owner={owner}", "-F", f"repo={name}", "-F", f"pr={number}")
        heads, issues, branches = set(), set(), set()
        if not isinstance(pages, list) or not pages:
            raise ValueError("unreadable PR")
        has_links = False
        for page in pages:
            if page.get("errors"):
                raise ValueError("incomplete PR response")
            pr = page["data"]["repository"]["pullRequest"]
            if pr["state"] != "OPEN":
                raise ValueError("PR is not open")
            heads.add(pr["headRefOid"])
            branch = pr["headRefName"]
            if not isinstance(branch, str) or not branch:
                raise ValueError("unreadable PR branch")
            branches.add(branch if pr["isCrossRepository"] is False and self.same_origin(pr) else "")
            links = pr["closingIssuesReferences"]
            has_links |= bool(links["nodes"])
            for issue in links["nodes"]:
                if issue["repository"]["nameWithOwner"].lower() == self.repo:
                    issues.add(issue["number"])
        if links["pageInfo"]["hasNextPage"] or len(heads) != 1 or len(branches) != 1:
            raise ValueError("PR changed or issue links are incomplete")
        head = heads.pop()
        if not SHA.fullmatch(head):
            raise ValueError("unreadable PR head")
        return head, issues, branches.pop(), has_links

    def check(self, number, head=None, scope=None, *, issue=None, unlinked_issue=None):
        current_head, issues, branch, has_links = self.pr(number)
        if issue is not None and issue not in issues:
            return {"approved": False, "why": "request issue is not linked to this PR"}
        if unlinked_issue is not None and (has_links or not re.fullmatch(rf"issue-{unlinked_issue}-.+", branch)):
            return {"approved": False, "why": "expected an unlinked same-repository workflow PR"}
        if head is not None and current_head != head:
            return {"approved": False, "headChanged": True, "why": "PR head changed after review"}
        sources = issues | {number}
        if unlinked_issue is not None:
            sources.add(unlinked_issue)
        comments = [comment for source in sorted(sources) for comment in self.comments(source)]
        expected = {"repo": self.repo, "pr": number, "head": current_head}
        if scope is not None:
            expected["scope"] = scope
        result = validate(comments, expected, self.permission, unlinked_issue=unlinked_issue)
        if unlinked_issue is not None:
            result.pop("headChanged", None)
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int)
    ap.add_argument("--head")
    ap.add_argument("--plan", help="JSON plan from merge-policy")
    ap.add_argument("--request", action="store_true", help="print a pinned request; no network or writes")
    ap.add_argument("--deps", action="store_true", help="enrich the dependency graph on stdin")
    args = ap.parse_args()
    if args.request:
        if not args.pr or not args.head or not SHA.fullmatch(args.head) or not args.plan:
            ap.error("request requires --pr, full --head and --plan")
        print(marker(request_for(args.repo, args.pr, args.head, scope_for(json.loads(args.plan)))))
        return
    if args.deps:
        graph = json.load(sys.stdin)
        github = GitHub(args.repo) if args.repo else None
        open_prs = None
        for entry in graph.values():
            entry["needsYouDone"] = False
            entry["approvalRefresh"] = False
            if not entry.get("needsYou") or github is None:
                continue
            try:
                comments = github.comments(entry["number"])
                blocks = trusted_blocks(comments, github.permission)
                blocks.sort(key=lambda c: timestamp(c.get("created_at")), reverse=True)
                if len(blocks) > 1 and timestamp(blocks[0]["created_at"]) == timestamp(blocks[1]["created_at"]):
                    entry["approvalWhy"] = "ambiguous newest human request"
                    continue
                request = parse_request(blocks[0]) if blocks else None
                issue = entry["number"]
                if request is not None:
                    if request["repo"] != github.repo:
                        continue
                    if timestamp(blocks[0]["updated_at"]) != timestamp(blocks[0]["created_at"]):
                        entry["approvalWhy"] = "approval request was edited; post a fresh request"
                        continue
                    result = github.check(request["pr"], request["head"], issue=issue)
                else:
                    if open_prs is None:
                        open_prs = github.open_prs()
                    candidates = [number for number, branch in open_prs.items()
                                  if re.fullmatch(rf"issue-{issue}-.+", branch)]
                    if len(candidates) != 1:
                        entry["approvalWhy"] = "expected one same-repository workflow PR"
                        continue
                    result = github.check(candidates[0], unlinked_issue=issue)
                entry["needsYouDone"] = result["approved"]
                entry["approvalRefresh"] = result.get("headChanged", False)
                entry["approvalWhy"] = result["why"]
            except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError):
                entry["approvalWhy"] = "approval evidence could not be verified"
        print(json.dumps(graph))
        return
    if not args.pr or not args.head or not args.plan:
        ap.error("check requires --pr, --head and --plan")
    try:
        result = GitHub(args.repo).check(args.pr, args.head, scope_for(json.loads(args.plan)))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError):
        result = {"approved": False, "why": "approval evidence could not be verified"}
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except github_read.ReadHalted as error:
        print(f"GitHub read halt: {error}", file=sys.stderr)
        sys.exit(github_read.HALTED)
