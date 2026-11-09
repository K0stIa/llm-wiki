"""Tests for the document/review checker, not the proposed knowledge service."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "verify.py"
SPEC = importlib.util.spec_from_file_location("wiki_design_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class CurrentReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.base = self.root / "specs/wiki-system"
        self.base.mkdir(parents=True)
        reads = []
        for name in VERIFY.CORE:
            path = self.base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source for " + name)
            reads.append({"path": f"<repo>/specs/wiki-system/{name}", "sha256": VERIFY.digest(path)})
        self.report = self.base / "report.md"
        self.report.write_text("## Verdict: READY-FOR-IMPLEMENTATION\n")
        self.receipt = self.base / "receipt.json"
        self.run = {"provider": "anthropic", "model": "claude-opus-5-5", "thinking": "high",
                    "status": "completed", "sha256": VERIFY.digest(self.report), "reads": reads}
        self.receipt.write_text(json.dumps(self.run))
        self.data = {"latest_design_review": {"verdict": "READY-FOR-IMPLEMENTATION",
                     "report": "specs/wiki-system/report.md", "receipt": "specs/wiki-system/receipt.json"}}

    def status(self) -> str:
        return VERIFY.latest_review_status(self.data, self.root)

    def test_matching_current_snapshot_is_ready(self) -> None:
        self.assertEqual(self.status(), "READY-FOR-IMPLEMENTATION")

    def test_new_failure_overrides_old_ready_report(self) -> None:
        self.data["latest_design_review"]["verdict"] = "NEEDS-REVISION"
        self.assertEqual(self.status(), "NEEDS-REVISION")

    def test_changed_reviewed_contract_is_stale(self) -> None:
        (self.base / "contract.d.ts").write_text("changed after review")
        self.assertEqual(self.status(), "STALE")

    def test_tampered_report_is_unverified(self) -> None:
        self.report.write_text("changed report")
        self.assertEqual(self.status(), "UNVERIFIED")

    def test_wrong_provider_or_reasoning_is_unverified(self) -> None:
        for field, value in [("provider", "github-copilot"), ("thinking", "medium")]:
            with self.subTest(field=field):
                changed = self.run | {field: value}
                self.receipt.write_text(json.dumps(changed))
                self.assertEqual(self.status(), "UNVERIFIED")

    def test_missing_core_read_is_stale(self) -> None:
        self.run["reads"] = self.run["reads"][:-1]
        self.receipt.write_text(json.dumps(self.run))
        self.assertEqual(self.status(), "STALE")

    def test_receipt_path_escape_is_rejected(self) -> None:
        self.data["latest_design_review"]["receipt"] = "../../outside.json"
        self.assertEqual(self.status(), "UNVERIFIED")

    def test_missing_latest_review_is_not_ready(self) -> None:
        self.assertEqual(VERIFY.latest_review_status({}, self.root), "UNREVIEWED")

    def test_malformed_latest_metadata_is_not_ready(self) -> None:
        self.assertEqual(VERIFY.latest_review_status({"latest_design_review": None}, self.root), "UNVERIFIED")

    def test_ready_metadata_cannot_override_failed_report(self) -> None:
        self.report.write_text("## Verdict: NEEDS-REVISION\n")
        self.run["sha256"] = VERIFY.digest(self.report)
        self.receipt.write_text(json.dumps(self.run))
        self.assertEqual(self.status(), "UNVERIFIED")

    def test_conflicting_verdicts_are_unverified_in_either_order(self) -> None:
        for first, second in [("READY-FOR-IMPLEMENTATION", "NEEDS-REVISION"),
                              ("NEEDS-REVISION", "READY-FOR-IMPLEMENTATION")]:
            with self.subTest(first=first):
                self.report.write_text(f"## Verdict: {first}\n\n## Verdict: {second}\n")
                self.run["sha256"] = VERIFY.digest(self.report)
                self.receipt.write_text(json.dumps(self.run))
                self.assertEqual(self.status(), "UNVERIFIED")

    def test_duplicate_ready_verdicts_are_unverified(self) -> None:
        self.report.write_text("## Verdict: READY-FOR-IMPLEMENTATION\n" * 2)
        self.run["sha256"] = VERIFY.digest(self.report)
        self.receipt.write_text(json.dumps(self.run))
        self.assertEqual(self.status(), "UNVERIFIED")

    def test_verdict_example_is_not_an_authoritative_leading_verdict(self) -> None:
        for prefix in ["```markdown\n", "Review is incomplete.\n\n"]:
            with self.subTest(prefix=prefix):
                self.report.write_text(prefix + "## Verdict: READY-FOR-IMPLEMENTATION\n")
                self.run["sha256"] = VERIFY.digest(self.report)
                self.receipt.write_text(json.dumps(self.run))
                self.assertEqual(self.status(), "UNVERIFIED")

    def test_conflicting_receipt_verdict_is_unverified(self) -> None:
        self.run["verdict"] = "NEEDS-REVISION"
        self.receipt.write_text(json.dumps(self.run))
        self.assertEqual(self.status(), "UNVERIFIED")

    def test_changed_reviewed_checker_or_tests_are_stale(self) -> None:
        for name in ["verify.py", "tests/contract.test.ts", "tests/test_verifier.py"]:
            with self.subTest(name=name):
                path = self.base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                original = path.read_text() if path.exists() else None
                path.write_text("changed after review")
                self.assertEqual(self.status(), "STALE")
                if original is not None:
                    path.write_text(original)

    def test_malformed_top_level_metadata_is_unverified(self) -> None:
        for data in [None, [], "not metadata"]:
            with self.subTest(data=data):
                self.assertEqual(VERIFY.latest_review_status(data, self.root), "UNVERIFIED")

    def test_wrong_model_or_incomplete_run_is_unverified(self) -> None:
        for field, value in [("model", "other-model"), ("status", "failed")]:
            with self.subTest(field=field):
                self.receipt.write_text(json.dumps(self.run | {field: value}))
                self.assertEqual(self.status(), "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
