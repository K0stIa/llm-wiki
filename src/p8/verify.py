#!/usr/bin/env python3
"""
P8: G8 gate — independent verifier for release.

Run as a FRESH session with no implementer context:
    python3 src/p8/verify.py

Checks all gates independently. Names tested artifact hashes, commands, exits,
failures, and remaining manual checks. Does NOT identify the working tree by
git HEAD SHA (dirty tree is not a commit); instead it hashes the actual files
being tested.

This is the independent gate — not the implementer's self-check.
No commit/push/publish from this script.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from hashlib import sha256


PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def run(cmd: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command with timeout. Defaults to PROJECT_ROOT unless cwd specified."""
    if cwd is None:
        cwd = PROJECT_ROOT
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=cwd
    )


def sha256file(path: Path) -> str:
    """SHA-256 of a file."""
    return sha256(path.read_bytes()).hexdigest()


def hash_artifacts(repo_dir: str = PROJECT_ROOT) -> dict[str, str]:
    """Hash the complete state being tested in G8: all changed tracked files,
    dependency lockfiles, and the frozen corpus. This identifies the exact
    dirty tree regardless of git HEAD.

    Returns {path_rel: sha256_hex}. Symlinks hash their target text, not
    recursively expanded dependencies; dangling links remain MISSING.
    """
    hashes = {}
    base = Path(repo_dir)
    inventory = subprocess.run(
        ["git", "-C", str(base), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True, check=True, timeout=10,
    )
    for raw in inventory.stdout.split(b"\0"):
        if raw:
            name = raw.decode()
            file = base / name
            if file.is_symlink() and file.exists():
                hashes[name] = sha256(b"symlink\0" + str(file.readlink()).encode()).hexdigest()
            else:
                hashes[name] = sha256file(file) if file.is_file() else "MISSING"

    # Dependency lockfile
    lockfile = base / "package-lock.json"
    if lockfile.exists():
        hashes["package-lock.json"] = sha256file(lockfile)

    # Package metadata
    pkg = base / "package.json"
    if pkg.exists():
        hashes["package.json"] = sha256file(pkg)

    # Frozen corpus
    corpus_dir = base / "research" / "eval-corpus" / "frozen" / "v1"
    if corpus_dir.exists():
        for f in corpus_dir.rglob("*"):
            if f.is_file():
                hashes[str(f.relative_to(base))] = sha256file(f)

    # All G8-deliverable specs
    for p in (base / "specs" / "wiki-system").rglob("*"):
        if p.is_file() and p.suffix == ".md":
            rel = str(p.relative_to(base))
            if rel not in hashes:
                hashes[rel] = sha256file(p)

    # All test files
    for p in (base / "tests" / "hypothesis").rglob("*.py"):
        if p.is_file():
            rel = str(p.relative_to(base))
            if rel not in hashes:
                hashes[rel] = sha256file(p)

    return hashes


def list_changed_files(repo_dir: str = PROJECT_ROOT) -> list[str]:
    """List tracked files that differ from HEAD."""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return [l for l in result.stdout.strip().splitlines() if l]


def verify_g0(repo_dir: str = PROJECT_ROOT):
    """G0: Baseline and answer model pinned."""
    results = []
    path = Path(repo_dir) / "specs" / "wiki-system" / "P0-BASELINE.md"
    with open(path) as f:
        text = f.read()
    assert "qwen3.8-35b-a3b-mtp-32k" in text, "Answer model not pinned"
    assert "local-llamacpp" in text, "Provider not pinned"
    assert "tiktoken_cl100k" in text, "Tokenizer not pinned"
    results.append("G0 answer model: pinned ✓")

    manifest = Path(repo_dir) / "research" / "eval-corpus" / "frozen" / "v1" / "manifest.json"
    assert manifest.exists(), "Corpus manifest missing"
    with open(manifest) as f:
        m = json.load(f)
    assert str(m["version"]) == "1", f"Corpus version not v1: {m['version']}"
    corpus_hash = sha256file(manifest.parent / "questions.json")
    results.append(f"G0 corpus: frozen v1 ({len(m.get('files', []))} files) ✓ "
                   f"SHA={corpus_hash[:12]}")
    return results


def verify_g1(repo_dir: str = PROJECT_ROOT):
    """G1: Durable core tests."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_g1_runtime.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G1 durable core: 4 tests pass ✓"]
    return [f"G1 failed: exit {r.returncode} — {r.stderr[:500]}"]


def verify_g2(repo_dir: str = PROJECT_ROOT):
    """G2: Recall and evidence gates."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_g2_recall.py tests/hypothesis/test_p2_hybrid_runtime.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G2 frozen corpus and real cached QMD hybrid runtime: checks pass ✓",
                "G2 evaluation: UNVERIFIED (bounded retrieval and synthetic runtime checks do not establish full answer-quality or frozen-holdout targets)"]
    return [f"G2 failed: exit {r.returncode} — {r.stderr[:500]}"]


def verify_g3(repo_dir: str = PROJECT_ROOT):
    """G3: Service boundary adversarial tests."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_g3_adversarial.py tests/hypothesis/test_bridge_recovery_runtime.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G3 service boundary: adversarial and real bridge/SQLite recovery checks pass ✓"]
    return [f"G3 failed: exit {r.returncode} — {r.stderr[:500]}"]


def verify_g4(repo_dir: str = PROJECT_ROOT):
    """G4 configuration checks only; this verifier does not consume live transcripts.
    Native MCP child execution is demonstrated separately in EVIDENCE.md.
    """
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_p4_wiki_integration.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G4 parent-child: configuration checks pass ✓",
                "G4 child execution: UNVERIFIED (live transcripts require separate review; not consumed here)"]
    return [f"G4 parent-child: FAIL — exit {r.returncode}: {r.stderr[:500]}"]


def verify_g5(repo_dir: str = PROJECT_ROOT):
    """G5: Codex CLI — config/capability only."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_p5_codex.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G5 Codex CLI: config/capability verified ✓",
                "G5 child execution: UNVERIFIED (configuration checks do not establish live approved wiki calls)"]
    return [f"G5 failed: exit {r.returncode} — {r.stderr[:500]}"]


def verify_g6(repo_dir: str = PROJECT_ROOT):
    """G6: Claude Code — config/schema only."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_p6_claude_code.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G6 Claude Code: config/schema verified ✓",
                "G6 child execution: UNVERIFIED (requires live Claude Code session)"]
    return [f"G6 failed: exit {r.returncode} — {r.stderr[:500]}"]


def verify_g7(repo_dir: str = PROJECT_ROOT):
    """G7: OpenCode — installed-schema only."""
    r = run("/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_p7_opencode.py -v",
            cwd=repo_dir)
    if r.returncode == 0:
        return ["G7 OpenCode: installed-schema verified ✓",
                "G7 child execution: UNVERIFIED (requires live OpenCode session)"]
    return [f"G7 failed: exit {r.returncode} — {r.stderr[:500]}"]


def _test_rollback(repo_dir: str = PROJECT_ROOT) -> list[str]:
    """Actual rollback/restore test in an ISOLATED temp repo.

    1. Clones HEAD to a temp directory.
    2. git checkout HEAD <file> to populate the working tree.
    3. Modifies ONLY the temp copy (never the real working tree).
    4. Restores via `git checkout -- <file>` in the temp repo.
    5. Verifies restored content == HEAD content.
    6. Deletes the temp repo.

    CRITICAL: this NEVER touches the real working tree.
    """
    results = []
    test_path = "src/mcp/transport.ts"  # committed implementation file
    if not (Path(repo_dir) / test_path).exists():
        return ["G8 rollback: SKIP — no test file available"]

    # Capture HEAD's content
    head_result = subprocess.run(
        ["git", "-C", str(repo_dir), "show", f"HEAD:{test_path}"],
        capture_output=True, text=True, timeout=10,
    )
    if head_result.returncode != 0:
        return [f"G8 rollback: SKIP — HEAD not found ({head_result.stderr[:100]})"]
    original_content = head_result.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tdp = Path(tmpdir)
        repo = tdp / "repo"

        # Clone (bare-ish — no files yet)
        clone_result = subprocess.run(
            ["git", "clone", "--no-checkout", repo_dir, str(repo)],
            capture_output=True, text=True, timeout=30,
        )
        if clone_result.returncode != 0:
            results.append(f"G8 rollback: FAIL — git clone: {clone_result.stderr[:200]}")
            return results

        # Get the file into the temp working tree
        checkout = subprocess.run(
            ["git", "checkout", "HEAD", test_path],
            capture_output=True, text=True, timeout=10, cwd=repo,
        )
        if checkout.returncode != 0:
            results.append(f"G8 rollback: FAIL — git checkout HEAD: {checkout.stderr[:200]}")
            return results

        clone_file = repo / test_path
        if not clone_file.exists():
            results.append("G8 rollback: SKIP — file absent from clone")
            return results

        # Verify initial content matches HEAD
        initial = clone_file.read_text()
        if initial != original_content:
            results.append(
                f"G8 rollback: FAIL — clone content != HEAD "
                f"({len(initial)} vs {len(original_content)} bytes)"
            )
            return results

        # Modify ONLY the temp copy
        modified = initial + "\n--- rollback-test-marker ---\n"
        clone_file.write_text(modified)

        # Restore via git checkout -- in the temp repo
        restore = subprocess.run(
            ["git", "checkout", "--", test_path],
            capture_output=True, text=True, timeout=10, cwd=repo,
        )
        if restore.returncode != 0:
            results.append(f"G8 rollback: FAIL — git checkout --: {restore.stderr[:200]}")
            return results

        # Verify restored content matches HEAD
        restored = clone_file.read_text()
        if restored == original_content:
            results.append("G8 rollback: OK — temp repo restored to HEAD ✓")
        else:
            results.append(
                f"G8 rollback: FAIL — temp copy not restored "
                f"({len(restored)} vs {len(original_content)} bytes)"
            )

        # Verify the marker is gone
        if "rollback-test-marker" in restored:
            results.append("G8 rollback: FAIL — marker still present")
        else:
            results.append("G8 rollback: marker removed (restore confirmed) ✓")

    return results


def verify_g8(repo_dir: str = PROJECT_ROOT):
    """G8: Release gate — sanitize, rollback, runbook, deliverables.
    Checks all artifacts, runs sanitizer (fail-closed on UNVERIFIABLE),
    and tests non-destructive rollback of a modified artifact.
    repo_dir allows testing from a temp clone.
    """
    results = []
    failures = []
    base = Path(repo_dir)

    # Sanitization (returns 0=clean, 1=leaks, 2=unverifiable)
    # FAIL-CLOSED: exit 2 (UNVERIFIABLE) is treated as FAIL, not PASS.
    r = run("python3 src/p8/sanitized-check.py", cwd=repo_dir)
    if r.returncode == 0:
        results.append("G8 sanitized: 0 corpus leaks ✓")
    elif r.returncode == 1:
        results.append(f"G8 sanitized: FAIL — {r.stdout.strip()}")
        failures.append("G8 sanitized: FAIL — leaks found")
    else:
        # exit 2 = UNVERIFIABLE — fail closed, NOT pass
        results.append(
            f"G8 sanitized: UNVERIFIABLE (exit {r.returncode}) "
            f"— corpus may not be frozen. FAIL-CLOSED (not PASS)."
        )
        failures.append(f"G8 sanitized: UNVERIFIABLE (exit {r.returncode})")

    # Release notes exist
    rp = base / "src" / "p8" / "RELEASING.md"
    if rp.exists():
        results.append(f"G8 release notes: exists ✓ (SHA={sha256file(rp)[:12]})")
    else:
        results.append("G8 release notes: FAIL — RELEASING.md missing")
        failures.append("G8 release notes: missing")

    # Deliverables
    deliverables = {
        "specs/wiki-system/P5-CODEX-CLI.md": "P5 spec",
        "tests/hypothesis/test_p5_codex.py": "P5 tests (20)",
        "src/p6/wiki-child-agent.json": "P6 child agent JSON",
        "src/p6/validate-config.py": "P6 validator",
        "tests/hypothesis/test_p6_claude_code.py": "P6 tests (18)",
        "src/p7/wiki-child-agent.json": "P7 child agent JSON",
        "src/p7/validate-schema.py": "P7 validator",
        "tests/hypothesis/test_p7_opencode.py": "P7 tests (15)",
        "src/p8/RELEASING.md": "P8 release notes",
        "src/p8/sanitized-check.py": "P8 sanitizer",
        "src/p8/verify.py": "P8 verifier",
        "tests/hypothesis/test_p8_sanitize.py": "P8 regression tests (7)",
    }
    missing = []
    for path, label in deliverables.items():
        if not (base / path).exists():
            missing.append(f"{label} ({path})")
    if missing:
        results.append(f"G8 deliverables: FAIL — missing: {', '.join(missing)}")
        failures.append(f"G8 deliverables: missing: {', '.join(missing)}")
    else:
        results.append(f"G8 deliverables: all {len(deliverables)} present ✓")

    # Non-destructive rollback test
    try:
        rollback_results = _test_rollback(repo_dir)
        for r in rollback_results:
            if "UNAVAILABLE" in r or "SKIP" in r or "unavailable" in r.lower():
                results.append(f"G8 rollback: ✗ UNAVAILABLE — {r}")
                failures.append("G8 rollback: UNAVAILABLE")
            elif "SKIP" in r and "no test file" in r.lower():
                results.append(f"G8 rollback: ✗ SKIP — no test file available")
                failures.append("G8 rollback: UNAVAILABLE — no test file")
            elif "FAIL" in r:
                # FAIL in rollback result also counts — not just UNAVAILABLE
                results.append(f"G8 rollback: ✗ FAIL — {r}")
                failures.append(f"G8 rollback: FAIL — {r}")
            else:
                results.append(r)
    except Exception as e:
        results.append(f"G8 rollback: ✗ UNAVAILABLE — {e}")
        failures.append(f"G8 rollback: UNAVAILABLE — {e}")

    return results


def main(repo_dir: str = PROJECT_ROOT):
    """Run the full G8 gate. repo_dir allows testing from a temp clone.
    Returns 0 (all verified), 1 (failure), or 2 (runtime evidence incomplete)."""
    # Identify the tested state by hashing actual artifacts, not git HEAD
    try:
        artifacts = hash_artifacts(repo_dir)
    except Exception as exc:
        print(f"FAIL: artifact inventory unavailable: {exc}")
        return 1
    print("G8 gate — verified artifacts (sha256):")
    for p, h in sorted(artifacts.items()):
        if h != "MISSING":
            print(f"  {p:<50} {h[:16]}...")
        else:
            print(f"  {p:<50} MISSING")
    print()

    all_results = []
    all_failures = [f"MISSING artifact: {p}" for p, digest in artifacts.items()
                    if digest == "MISSING"]
    for name, fn in [("G0", verify_g0), ("G1", verify_g1), ("G2", verify_g2),
                     ("G3", verify_g3), ("G4", verify_g4), ("G5", verify_g5),
                     ("G6", verify_g6), ("G7", verify_g7), ("G8", verify_g8)]:
        try:
            results = fn(repo_dir)
            if not results:
                results = [f"{name}: FAIL empty verification result"]
        except Exception as exc:
            results = [f"{name}: FAIL {type(exc).__name__}: {exc}"]
        all_results.extend(results)
        for r in results:
            # Only explicit success or a named child-runtime limitation is accepted.
            # Check ALL results for failure indicators (literal markers only,
            # not status labels like "UNVERIFIED" or "missing").
            # Must catch the exact emitted forms from each gate:
            #   "✗" (literal cross marker)
            #   "FAIL" (uppercase, e.g. from deliverables missing)
            #   "failed" (lowercase, e.g. "G1 failed: exit 1")
            #   "unavailable" (lowercase, e.g. "rollback: UNAVAILABLE")
            #   "SKIP" (e.g. "G8 rollback: SKIP — no test file")
            #   "no test file" (raw rollback result)
            r_lower = r.lower()
            is_failure = (
                "✗" in r
                or "FAIL" in r
                or "failed" in r_lower
                or "unavailable" in r_lower
                or "SKIP" in r
                or "no test file" in r_lower
                or ("✓" not in r and "UNVERIFIED" not in r)
            )
            if is_failure:
                all_failures.append(f"{name}: {r}")
            status = "UNVERIFIED" if "UNVERIFIED" in r else ("✓" if not is_failure else "✗")
            print(f"  {name} {status}: {r}")

    print("=" * 60)
    if all_failures:
        print(f"FAIL: {len(all_failures)} gate(s) failed")
        for f in all_failures:
            print(f"  {f}")
        return 1

    # Check for UNVERIFIED gates (expected for config-only scope)
    unverified = [r for r in all_results if "UNVERIFIED" in r or "unverified" in r.lower()]
    if unverified:
        print(f"INCOMPLETE: {len(unverified)} runtime checks lack evidence")
        for v in unverified:
            print(f"  {v}")
        print("Release readiness is not established.")
        return 2
    print("GATE PASS: all requested checks verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
