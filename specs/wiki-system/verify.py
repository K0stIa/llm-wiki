#!/usr/bin/env python3
"""Check design integrity/current review status, not application runtime gates."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
CORE = ("ARCHITECTURE.md", "contract.d.ts", "DELIVERY.md", "verify.py",
        "tests/contract.test.ts", "tests/test_verifier.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def repository_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "Path escaped repository")
    require(path.is_file(), f"Missing file: {name}")
    return path


def latest_review_status(data: dict, root: Path) -> str:
    """A historical READY cannot override a newer failure or changed source."""
    if not isinstance(data, dict):
        return "UNVERIFIED"
    latest = data.get("latest_design_review", {})
    if not isinstance(latest, dict):
        return "UNVERIFIED"
    if latest.get("verdict") != "READY-FOR-IMPLEMENTATION":
        return "NEEDS-REVISION" if latest.get("verdict") == "NEEDS-REVISION" else "UNREVIEWED"
    try:
        report = repository_file(root, latest["report"])
        receipt_path = repository_file(root, latest["receipt"])
        receipt = json.loads(receipt_path.read_text())
        identity = (receipt["provider"], receipt["model"], receipt["thinking"], receipt["status"])
        require(identity == ("anthropic", "claude-opus-5-5", "high", "completed"), "Wrong reviewer identity")
        require(digest(report) == receipt["sha256"], "Review report hash mismatch")
        lines = report.read_text().splitlines()
        verdicts = [line for line in lines if line.startswith("## Verdict:")]
        require(verdicts == ["## Verdict: READY-FOR-IMPLEMENTATION"], "Ambiguous or non-READY verdict")
        require(next((line for line in lines if line.strip()), "") == verdicts[0], "Verdict must lead report")
        require(receipt.get("verdict", latest["verdict"]) == latest["verdict"], "Receipt verdict mismatch")
        reads = {item["path"]: item["sha256"] for item in receipt["reads"]}
        for name in CORE:
            relative = f"specs/wiki-system/{name}"
            current = repository_file(root, relative)
            if reads.get(f"<repo>/{relative}") != digest(current):
                return "STALE"
        return "READY-FOR-IMPLEMENTATION"
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return "UNVERIFIED"


def check(require_ready: bool = False) -> int:
    required = [
        "README.md", "ARCHITECTURE.md", "DELIVERY.md", "RATIONALE.md",
        "GROUNDING.md", "WORKFLOW.md", "VERIFICATION.md", "contract.d.ts",
        "provenance.json", "OPUS_FIXES.md", "tests/contract.test.ts",
        "tests/test_verifier.py", "validation.json",
        "arena/candidate-a.md", "arena/candidate-b.md", "arena/cross-judge.md",
        "arena/design-review.md", "arena/final-review.md", "arena/opus-5-5-review.md",
    ]
    for name in required:
        require((BASE / name).is_file(), f"Missing artifact: {name}")
    links = 0
    for path in BASE.rglob("*.md"):
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            require((path.parent / target.split("#", 1)[0]).is_file(), f"Broken link in {path.name}: {target}")
            links += 1
    architecture = (BASE / "ARCHITECTURE.md").read_text()
    delivery = (BASE / "DELIVERY.md").read_text()
    contract = (BASE / "contract.d.ts").read_text()
    for token in ["SQLite", "BEGIN IMMEDIATE", "outbox", "QMD", "MCP", "Origin",
                  "across all operation kinds", "FTS runs inside that transaction",
                  "Authorize every expanded target", "ReviewDigest", "stale-epoch",
                  "24,000", "separate OS identity", "before sending", "never counters"]:
        require(token in architecture, f"Missing architecture constraint: {token}")
    for gate in range(9):
        require(f"G{gate}" in delivery, f"Missing gate G{gate}")
    for token in ["held-out", "Pi -> Codex CLI -> Claude Code -> OpenCode", "zero silent",
                  "150 seconds", "twelve working days", "same numeric sequence",
                  "curator-targeted", "30 held-out", "post-hoc", "24,000-byte", "Rollback"]:
        require(token in delivery, f"Missing delivery constraint: {token}")
    for token in ["AuthorityEpoch", "CommitSequence", "reviewDigest", "ReviewDigest", "maxBytes",
                  "PageSnapshot", "pendingProposals", "private-evidence", 'kind: "not-ready"']:
        require(token in contract, f"Missing domain invariant: {token}")
    require(not re.search(r"\bany\b|\bas\b", contract), "Contract uses any or a cast")
    for removed in ["hybrid-with-lexical-tail", '"incomplete"', '"scan-budget"', '"allow-degraded"']:
        require(removed not in contract, f"Retired API still present: {removed}")
    provenance = json.loads((BASE / "provenance.json").read_text())
    for record in provenance["artifacts"]:
        path = repository_file(ROOT, record["path"])
        require(digest(path) == record["sha256"], f"Artifact hash mismatch: {record['path']}")
    status = latest_review_status(provenance, ROOT)
    print(f"PASS: {len(required)} artifacts, {links} local links and recorded hashes")
    print(f"LATEST DESIGN REVIEW: {status}")
    require(not require_ready or status == "READY-FOR-IMPLEMENTATION", f"Current design is not ready: {status}")
    print("NOT RUN: application gates G0-G8 or production host integrations")
    return 0


if __name__ == "__main__":
    try:
        require(sys.argv[1:] in ([], ["--require-ready"]), "Usage: verify.py [--require-ready]")
        sys.exit(check(require_ready="--require-ready" in sys.argv))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
