"""Runtime decision regressions. These are controlled tests, not host certification."""
import importlib.util
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("gate_under_test", ROOT / "src/p8/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve().is_relative_to(ROOT)
    return module


@pytest.fixture
def current_copy(tmp_path):
    repo = tmp_path / "current code with spaces"
    subprocess.run(["git", "clone", "--quiet", str(ROOT), str(repo)], check=True,
                   capture_output=True, timeout=30)
    # Overlay dirty and untracked current code, including specs (not spec).
    for name in ("src", "tests", "specs", "research"):
        shutil.copytree(ROOT / name, repo / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / name, repo / name)
    for name in ("src/p8/verify.py", "specs/wiki-system/DELIVERY.md"):
        assert (repo / name).read_bytes() == (ROOT / name).read_bytes()
    return repo


def control_other_gates(monkeypatch, verifier, except_gate):
    """Isolate the decision under test; don't claim mocked gates were executed."""
    for n in range(9):
        if n != except_gate:
            monkeypatch.setattr(verifier, f"verify_g{n}",
                                lambda repo: ["controlled unrelated gate ✓"])


@pytest.mark.parametrize("gate", range(1, 8))
def test_actual_subprocess_failure_reaches_main(gate, verifier, current_copy, monkeypatch, capsys):
    control_other_gates(monkeypatch, verifier, gate)
    real_run = verifier.run
    calls = []

    def command_result(command, cwd=None):
        calls.append(command)
        # Execute a real process, retaining the actual gate's result formatting.
        return subprocess.run([sys.executable, "-c", "import sys; sys.exit(7)"],
                              cwd=cwd, capture_output=True, text=True, timeout=10)

    monkeypatch.setattr(verifier, "run", command_result)
    assert verifier.main(str(current_copy)) == 1
    output = capsys.readouterr().out
    expected = (f"G{gate} parent-child: FAIL — exit 7" if gate == 4
                else f"G{gate} failed: exit 7")
    assert expected in output
    assert "GATE PASS" not in output
    assert len(calls) == 1

    # Same main and same real gate, successful command control.
    monkeypatch.setattr(verifier, "run", lambda command, cwd=None: subprocess.run(
        [sys.executable, "-c", "pass"], cwd=cwd, capture_output=True, text=True, timeout=10))
    # G2 and G4-G7 still lack runtime evidence; successful commands must
    # produce INCOMPLETE rather than silently certify those gates.
    expected_control = 0 if gate in (1, 3) else 2
    assert verifier.main(str(current_copy)) == expected_control
    monkeypatch.setattr(verifier, "run", real_run)


@pytest.mark.parametrize("fault", ["missing", "restore-failure", "exception"])
def test_rollback_final_decision(fault, verifier, current_copy, monkeypatch, capsys):
    control_other_gates(monkeypatch, verifier, 8)
    # Hold inventory constant so a missing file cannot fail main for an unrelated
    # inventory reason instead of the rollback decision under test.
    inventory = verifier.hash_artifacts(str(current_copy))
    monkeypatch.setattr(verifier, "hash_artifacts", lambda repo: inventory)
    # Real sanitizer, complete deliverables, and real rollback success in this SAME fixture.
    assert verifier.main(str(current_copy)) == 0
    healthy = capsys.readouterr().out
    assert "G8 sanitized: 0 corpus leaks ✓" in healthy
    assert "G8 deliverables: all 12 present ✓" in healthy
    assert "temp repo restored to HEAD ✓" in healthy

    if fault == "missing":
        (current_copy / "src/mcp/transport.ts").unlink()
    elif fault == "restore-failure":
        original = verifier.subprocess.run

        def fail_restore(args, *a, **kw):
            if isinstance(args, list) and args[:3] == ["git", "checkout", "--"]:
                return subprocess.CompletedProcess(args, 9, "", "injected restore failure")
            return original(args, *a, **kw)

        monkeypatch.setattr(verifier.subprocess, "run", fail_restore)
    else:
        def unavailable(repo):
            raise OSError("injected rollback exception")
        monkeypatch.setattr(verifier, "_test_rollback", unavailable)

    assert verifier.main(str(current_copy)) == 1
    output = capsys.readouterr().out
    assert "G8 sanitized: 0 corpus leaks ✓" in output
    assert "G8 deliverables: all 12 present ✓" in output
    assert "GATE PASS" not in output
    reason = {"missing": "no test file available", "restore-failure": "injected restore failure",
              "exception": "injected rollback exception"}[fault]
    assert reason in output


def test_rollback_preserves_its_dirty_source(verifier, current_copy):
    source = current_copy / "src/mcp/transport.ts"
    source.write_bytes(source.read_bytes() + b"\n// dirty source sentinel\n")
    before = sha256(source.read_bytes()).hexdigest()
    results = verifier._test_rollback(str(current_copy))
    assert any("temp repo restored to HEAD ✓" in r for r in results), results
    assert any("marker removed" in r for r in results), results
    assert sha256(source.read_bytes()).hexdigest() == before
