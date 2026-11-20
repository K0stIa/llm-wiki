"""Receipt validation and gate status (src/verification). Tier A, no subprocess models."""
import copy
import json
import os
import re
import stat
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


def test_identity_binds_dirty_source_bytes_without_changing_clean_shape(tmp_path):
    R._git(tmp_path, "init", "-q")
    source = tmp_path / "src" / "engine.ts"
    source.parent.mkdir()
    source.write_text("original")
    (tmp_path / ".gitignore").write_text("/src/cache\n")
    R._git(tmp_path, "add", ".")
    R._git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture")
    clean = R.current_identity(tmp_path)
    assert not clean["dirty"]
    assert "dirty_source_sha256" not in clean

    R._git(tmp_path, "config", "core.filemode", "false")
    source.chmod(0o755)
    (source.parent / "cache").symlink_to(tmp_path.parent / "unused")
    assert R.dirty_paths(tmp_path) == []
    assert R.current_identity(tmp_path) == clean

    source.write_text("first edit")
    first = R.current_identity(tmp_path)
    source.write_text("second edit")
    second = R.current_identity(tmp_path)
    assert first["dirty_paths"] == second["dirty_paths"] == ["src/engine.ts"]
    assert first["dirty_source_sha256"] != second["dirty_source_sha256"]
    assert R.identity_key(first) == R.identity_key(second) == R.identity_key(clean)

    source.chmod(0o644)
    mode_edit = R.current_identity(tmp_path)
    assert mode_edit["dirty_paths"] == second["dirty_paths"]
    assert mode_edit["dirty_source_sha256"] != second["dirty_source_sha256"]

    source.unlink()
    deleted = R.current_identity(tmp_path)
    (source.parent / "cache").unlink()
    source.parent.rmdir()
    source.parent.write_text("regular replacement")
    assert R._checkout_file(tmp_path, "src/engine.ts") == {}
    assert R.current_identity(tmp_path)["dirty_source_sha256"] != deleted["dirty_source_sha256"]
    source.parent.unlink()
    source.parent.symlink_to(tmp_path.parent)
    with pytest.raises(R.ReceiptError, match="checkout symlink src;"):
        R.current_identity(tmp_path)


def test_pinned_input_hashes_confined_symlink(tmp_path):
    R._git(tmp_path, "init", "-q")
    target = tmp_path / "config"
    target.write_text("pinned configuration")
    link = tmp_path / "pyproject.toml"
    link.symlink_to(target.name)
    R._git(tmp_path, "add", ".")
    R._git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture")
    identity = R.current_identity(tmp_path)
    assert not identity["dirty"]
    assert identity["inputs"][link.name] == R.sha256_file(target)
    target.unlink()
    target.symlink_to("../outside")
    with pytest.raises(R.ReceiptError, match="checkout symlink pyproject.toml;"):
        R.current_identity(tmp_path)


@pytest.mark.parametrize("target", [
    "config", "config/", "config/.", "dir/./../config", "config/../config",
    "alias", "alias/", "directory/../config", "invalid",
])
def test_pinned_input_link_matches_stat(tmp_path, target, monkeypatch):
    config = tmp_path / "config"
    config.write_text("pinned configuration")
    (tmp_path / "dir").mkdir()
    (tmp_path / "alias").symlink_to("config")
    (tmp_path / "directory").symlink_to("dir/.")
    (tmp_path / "invalid").symlink_to("config/")
    link = tmp_path / "pyproject.toml"
    link.symlink_to(target)
    try:
        is_regular = stat.S_ISREG(os.stat(link).st_mode)
    except NotADirectoryError:
        is_regular = False
    assert link.is_file() == is_regular
    expected = R.sha256_file(config) if is_regular else "MISSING"

    def reject_digest(*args):
        pytest.fail("a directory-required target must not be read")

    if not is_regular:
        monkeypatch.setattr(R.hashlib, "file_digest", reject_digest)
    assert R._checkout_file(tmp_path, link.name, allow_links=True).get("sha256", "MISSING") == expected


def test_identity_covers_rename_sources_modes_and_non_utf8_paths(tmp_path):
    R._git(tmp_path, "init", "-q")
    source = tmp_path / "src" / "engine \udcff.ts"
    source.parent.mkdir()
    source.write_text("original")
    R._git(tmp_path, "add", ".")
    R._git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture")
    R._git(tmp_path, "mv", str(source), "note")
    moved = R.current_identity(tmp_path)
    assert moved["dirty_paths"] == ["note", "src/engine \udcff.ts"]
    source.write_text("recreated")
    unstaged = R.current_identity(tmp_path)
    assert unstaged["dirty_paths"] == moved["dirty_paths"]
    assert unstaged != moved
    R._git(tmp_path, "add", str(source))
    staged = R.current_identity(tmp_path)
    source.chmod(0o755)
    assert R.current_identity(tmp_path) != staged


@pytest.mark.parametrize("name", ["src", "src/engine.ts", "tsconfig.json"])
def test_identity_refuses_untracked_staged_and_committed_source_links(tmp_path, name):
    root = tmp_path / "checkout"
    root.mkdir()
    R._git(root, "init", "-q")
    R._git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "fixture")
    link = root / name
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(R.ReceiptError, match=f"checkout symlink {re.escape(name)};"):
        R.current_identity(root)
    R._git(root, "add", ".")
    link.unlink()
    link.write_text("regular working-tree replacement")
    with pytest.raises(R.ReceiptError, match=f"checkout symlink {re.escape(name)};"):
        R.current_identity(root)
    link.unlink()
    link.symlink_to(tmp_path, target_is_directory=True)
    R._git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "link")
    assert R.dirty_paths(root) == []
    with pytest.raises(R.ReceiptError, match=f"checkout symlink {re.escape(name)};") as error:
        R.current_identity(root)
    assert str(tmp_path) not in str(error.value)


def test_dirty_digest_refuses_file_changed_during_read(tmp_path, monkeypatch):
    source = tmp_path / "engine.ts"
    source.write_text("first")
    file_digest = R.hashlib.file_digest

    def changing_digest(stream, algorithm):
        result = file_digest(stream, algorithm)
        source.write_text("second")
        return result

    monkeypatch.setattr(R.hashlib, "file_digest", changing_digest)
    with pytest.raises(R.ReceiptError, match="changed while reading engine.ts"):
        R._dirty_source_digest(tmp_path, ["engine.ts"])


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


def test_trace_checkout_digest_binds_links_and_only_confined_bytes(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside")
    target = root / "target"
    target.write_text("inside")
    (root / "external").symlink_to("../outside")
    (root / "internal").symlink_to(target)
    trace_paths = ["external", "internal"]
    original = R.dirty_checkout_digest(root, trace_paths)
    outside.write_text("changed outside")
    assert R.dirty_checkout_digest(root, trace_paths) == original
    target.write_text("changed inside")
    changed = R.dirty_checkout_digest(root, trace_paths)
    assert changed != original
    (root / "external").unlink()
    (root / "external").symlink_to(outside)
    assert R.dirty_checkout_digest(root, trace_paths) != changed
