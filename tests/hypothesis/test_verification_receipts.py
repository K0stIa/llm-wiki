"""Receipt validation and gate status (src/verification). Tier A, no subprocess models."""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "verification"))
import receipts as R  # noqa: E402

COMMIT = "a" * 40
INPUTS = {name: "0" * 64 for name in R.IDENTITY_INPUTS}
RUNTIME = {"python": "3.12.3", "node": "v22.23.2", "platform": "Linux-x86_64"}
MODEL = {"sha256": "b" * 64}


def identity(**overrides):
    base = {"commit": COMMIT, "dirty": False, "dirty_paths": [], "inputs": dict(INPUTS),
            "runtime": dict(RUNTIME), "model": None}
    base.update(overrides)
    return base


def receipt(tier="a", outcomes=None, deterministic=True, finished="2026-11-15T10:00:00+00:00", **ident):
    outcomes = outcomes if outcomes is not None else [{"id": "tests/x.py::test_ok", "outcome": "passed"}]
    model = MODEL if tier == "b" else None
    r = {"schema": R.RECEIPT_SCHEMA, "tier": tier, "run_id": f"run-{finished}", "started": finished,
         "finished": finished, "identity": identity(model=model, **ident),
         "commands": [{"argv": ["pytest"], "exit": 0}], "repeat": 2, "deterministic": deterministic,
         "outcomes": outcomes, "outcomes_sha256": R.sha256_json(outcomes)}
    R.validate_receipt(r)
    return r


CURRENT = identity(model=MODEL)
CHECK = {"id": "x", "tier": "a", "tests": ["tests/x.py::"]}


def status(check, receipts, current=CURRENT):
    return R.check_status(check, receipts, current)[0]


def test_pass_requires_clean_current_receipt_with_matching_passes():
    assert status(CHECK, [receipt()]) == "PASS"


def test_check_without_tests_is_missing_even_with_receipts():
    assert status({**CHECK, "tests": []}, [receipt()]) == "MISSING"


def test_no_receipt_for_tier_is_missing():
    assert status({**CHECK, "tier": "c"}, [receipt()]) == "MISSING"


@pytest.mark.parametrize("field,value", [
    ("commit", "c" * 40),
    ("inputs", {**INPUTS, "uv.lock": "1" * 64}),
    ("runtime", {**RUNTIME, "node": "v24.0.0"}),
])
def test_identity_mismatch_is_stale(field, value):
    assert status(CHECK, [receipt(**{field: value})]) == "STALE"


def test_dirty_tree_receipt_never_counts():
    assert status(CHECK, [receipt(dirty=True, dirty_paths=["src/x.py"])]) == "EXPLORATORY"


def test_failure_and_error_fail():
    for outcome in ("failed", "error"):
        r = receipt(outcomes=[{"id": "tests/x.py::a", "outcome": "passed"},
                              {"id": "tests/x.py::b", "outcome": outcome}])
        assert status(CHECK, [r]) == "FAIL"


def test_skipped_is_not_a_pass():
    assert status(CHECK, [receipt(outcomes=[{"id": "tests/x.py::a", "outcome": "skipped"}])]) == "MISSING"


def test_nondeterministic_run_fails():
    assert status(CHECK, [receipt(deterministic=False)]) == "FAIL"


def test_unmatched_selector_is_missing():
    assert status({**CHECK, "tests": ["tests/other.py::"]}, [receipt()]) == "MISSING"


def test_latest_clean_receipt_wins():
    old_fail = receipt(outcomes=[{"id": "tests/x.py::a", "outcome": "failed"}], finished="2026-11-15T09:00:00+00:00")
    new_pass = receipt(finished="2026-11-15T11:00:00+00:00")
    assert status(CHECK, [old_fail, new_pass]) == "PASS"
    assert status(CHECK, [new_pass, receipt(outcomes=[{"id": "tests/x.py::a", "outcome": "failed"}],
                                            finished="2026-11-15T12:00:00+00:00")]) == "FAIL"


def test_tier_b_requires_approved_model_hash():
    check = {**CHECK, "tier": "b"}
    assert status(check, [receipt(tier="b")]) == "PASS"
    assert status(check, [receipt(tier="b")], identity(model={"sha256": "c" * 64})) == "STALE"


def test_measurements_and_regular_tier_receipts_do_not_replace_each_other():
    measurement = "g2.answer-quality"
    outcomes = [{"id": measurement, "outcome": "failed"}]
    measured = receipt(tier="b", outcomes=outcomes, finished="2026-11-15T11:00:00+00:00")
    measured["measurement"] = {"check": measurement, "report_sha256": "a" * 64}
    R.validate_receipt(measured)
    tier_run = receipt(tier="b", finished="2026-11-15T12:00:00+00:00")
    check = {"id": measurement, "tier": "b", "tests": [], "measurement": True}
    assert status(check, [tier_run, measured]) == "FAIL"
    assert status(check, [tier_run]) == "MISSING"
    assert status({**CHECK, "tier": "b"}, [measured, receipt(tier="b")]) == "PASS"
    assert status(check, [{**measured, "identity": {**measured["identity"], "dirty": True}}]) == "EXPLORATORY"
    unbound = {**measured, "measurement": {"check": "g2.recall-thresholds", "report_sha256": "a" * 64}}
    with pytest.raises(R.ReceiptError):
        R.validate_receipt(unbound)


def test_measurement_receipt_records_report_hash_without_report_contents(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    report.write_text('{"private_placeholder":"synthetic-test"}')
    directory = tmp_path / "receipts"
    monkeypatch.setattr(R, "RECEIPT_DIR", directory)
    path = R.write_measurement("g2.recall-thresholds", CURRENT, "2026-11-15T10:00:00+00:00", report,
                               True, ["python3", "src/eval/measure_v2.py", "--subset", "holdout"])
    records, errors = R.load_receipts(directory)
    assert not errors
    assert records[0]["measurement"]["report_sha256"] == R.sha256_file(report)
    assert "synthetic-test" not in path.read_text()
    check = {"id": "g2.recall-thresholds", "tier": "b", "tests": [], "measurement": True}
    assert status(check, records) == "PASS"


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(schema="other"),
    lambda r: r.update(tier="z"),
    lambda r: r["identity"].update(commit="short"),
    lambda r: r["identity"]["inputs"].pop("uv.lock"),
    lambda r: r["outcomes"].append({"id": "tests/x.py::extra", "outcome": "passed"}),
    lambda r: r["outcomes"][0].update(outcome="maybe"),
    lambda r: r.update(commands=[]),
    lambda r: r.update(repeat=0),
])
def test_malformed_or_tampered_receipts_are_rejected(mutate):
    r = copy.deepcopy(receipt())
    mutate(r)
    with pytest.raises(R.ReceiptError):
        R.validate_receipt(r)


def test_tier_b_receipt_without_model_is_rejected():
    r = copy.deepcopy(receipt(tier="b"))
    r["identity"]["model"] = None
    with pytest.raises(R.ReceiptError):
        R.validate_receipt(r)


def test_malformed_receipt_file_forces_failure_exit(tmp_path):
    (tmp_path / "bad.json").write_text("{}")
    (tmp_path / "good.json").write_text(json.dumps(receipt()))
    receipts, problems = R.load_receipts(tmp_path)
    assert len(receipts) == 1 and len(problems) == 1
    rows = R.evaluate([{"gate": "G1", "checks": [CHECK]}], receipts, CURRENT)
    assert rows[0]["status"] == "PASS"
    assert R.exit_code(rows, problems) == 1


def test_exit_codes():
    row = lambda s: {"status": s}
    assert R.exit_code([row("PASS")], []) == 0
    assert R.exit_code([row("PASS"), row("MISSING")], []) == 2
    assert R.exit_code([row("STALE"), row("FAIL")], []) == 1
    assert R.exit_code([], []) == 2


def test_dirty_paths_exempt_generated_evidence(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    (tmp_path / ".verification").mkdir()
    (tmp_path / ".verification" / "r.json").write_text("{}")
    assert R.dirty_paths(tmp_path) == []
    (tmp_path / "src.py").write_text("x")
    assert R.dirty_paths(tmp_path) == ["src.py"]


# ─── gates.json must stay consistent with the real tests ──────────────

GATES = R.load_gates()


def test_gates_cover_g0_through_g8():
    assert [g["gate"] for g in GATES] == [f"G{i}" for i in range(9)]


def test_every_selector_resolves_to_an_existing_test():
    for gate in GATES:
        for check in gate["checks"]:
            for selector in check["tests"]:
                path, _, name = selector.partition("::")
                if path == "typecheck":
                    assert (ROOT / name).is_file(), f"{check['id']}: missing {name}"
                    continue
                file = ROOT / path
                assert file.is_file(), f"{check['id']}: missing file {path}"
                if name and file.suffix == ".py":
                    assert re.search(rf"^\s*def {re.escape(name)}\(", file.read_text(), re.M), \
                        f"{check['id']}: no test {name} in {path}"


def test_every_test_file_is_mapped_to_a_gate():
    selectors = {s.split("::")[0] for g in GATES for c in g["checks"] for s in c["tests"]}
    files = {str(p.relative_to(ROOT)) for p in (ROOT / "tests" / "hypothesis").glob("test_*.py")}
    files |= {str(p.relative_to(ROOT)) for p in (ROOT / "tests" / "runtime").glob("*.test.mjs")}
    assert files - selectors == set()


def test_tier_b_and_c_tests_are_marked_consistently():
    """A check's tier must match the pytest marker of the tests it selects."""
    for gate in GATES:
        for check in gate["checks"]:
            for selector in check["tests"]:
                path = selector.split("::")[0]
                if path == "typecheck" or not path.endswith(".py"):
                    assert check["tier"] == "a", f"{check['id']}: node tests are tier a"
                    continue
                text = (ROOT / path).read_text()
                module_mark = re.search(r"^pytestmark = pytest\.mark\.tier_([bc])", text, re.M)
                name = selector.split("::")[1]
                func_mark = name and re.search(rf"@pytest\.mark\.tier_([bc])\s*\ndef {re.escape(name)}\(", text)
                tier = (func_mark or module_mark).group(1) if (func_mark or module_mark) else "a"
                assert tier == check["tier"], f"{check['id']}: {selector} is tier {tier}"
