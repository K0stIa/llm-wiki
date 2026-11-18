"""Sanitizer and artifact inventory tests, rooted in the code under test."""
import importlib.util
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/p8/sanitized-check.py"


def run_check(cwd):
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("corpus_state", ["missing", "empty"])
def test_no_corpus_is_unverifiable(tmp_path, corpus_state):
    if corpus_state == "empty":
        frozen = tmp_path / "research/eval-corpus/frozen/v1"
        frozen.mkdir(parents=True)
        (frozen / "manifest.json").write_text(json.dumps({"version": "1"}))
        for name in ("questions.json", "documents.json"):
            (frozen / name).write_text("[]")
    result = run_check(tmp_path)
    assert result.returncode == 2
    assert "UNVERIFIABLE" in result.stdout


def test_synthetic_leak_is_detected(tmp_path):
    text = "Synthetic non-private regression sentence. " * 4
    frozen = tmp_path / "research/eval-corpus/frozen/v1"
    frozen.mkdir(parents=True)
    (frozen / "manifest.json").write_text(json.dumps({"version": "1"}))
    (frozen / "questions.json").write_text(json.dumps([{"query": text}]))
    (frozen / "documents.json").write_text(json.dumps([{"body":"A separate synthetic corpus document."}]))
    artifact = tmp_path / "src/p8/report.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("No matching text")
    assert run_check(tmp_path).returncode == 0
    artifact.write_text(text)
    assert run_check(tmp_path).returncode == 1


def test_current_copy_is_scanned():
    result = run_check(ROOT)
    assert result.returncode == 0, result.stdout
    assert "Scanning" in result.stdout
    assert "0 leaks" in result.stdout


def test_hash_inventory_covers_current_files():
    spec = importlib.util.spec_from_file_location("verifier_inventory", ROOT / "src/p8/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hashes = module.hash_artifacts(str(ROOT))
    # Check exact file membership and digests, not additive counts with overlaps.
    expected = set()
    for folder in ("src", "tests/hypothesis", "specs/wiki-system", "research/eval-corpus/frozen/v1"):
        expected.update(str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob("*")
                        if p.is_file() and p.suffix in (".py", ".ts", ".md", ".json", ".sql", ".yaml"))
    expected.update(("package.json", "package-lock.json"))
    assert "specs/wiki-system/DELIVERY.md" in expected
    assert expected <= hashes.keys(), sorted(expected - hashes.keys())
    for name in expected:
        assert hashes[name] == sha256((ROOT / name).read_bytes()).hexdigest(), name


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_symlink_inventory_is_not_a_missing_artifact(tmp_path, target_kind):
    spec = importlib.util.spec_from_file_location("verifier_links", ROOT / "src/p8/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    target = tmp_path / "dependency"
    if target_kind == "directory":
        target.mkdir()
    else:
        target.write_text("synthetic dependency")
    link = repo / "dependency-link"
    link.symlink_to(target, target_is_directory=target_kind == "directory")
    expected = sha256(b"symlink\0" + str(link.readlink()).encode()).hexdigest()
    assert module.hash_artifacts(str(repo))["dependency-link"] == expected
    if target_kind == "directory":
        target.rmdir()
    else:
        target.unlink()
    assert module.hash_artifacts(str(repo))["dependency-link"] == "MISSING"

@pytest.mark.parametrize('field,text',[('query','Short private question?'),('body','Private document body only. '*5)])
def test_individual_corpus_fields_cannot_leak(tmp_path,field,text):
    frozen=tmp_path/'research/eval-corpus/frozen/v1'; frozen.mkdir(parents=True)
    (frozen/'manifest.json').write_text('{"version":"1"}')
    (frozen/'questions.json').write_text(json.dumps([{'query':text if field=='query' else 'Unrelated question', 'gold_sources':['private/source.md']}]))
    (frozen/'documents.json').write_text(json.dumps([{'body':text if field=='body' else 'Unrelated body','title':'Different title'}]))
    artifact=tmp_path/'src/p8/report.md'; artifact.parent.mkdir(parents=True);artifact.write_text(text)
    assert run_check(tmp_path).returncode==1

@pytest.mark.parametrize('fault',['missing','malformed','empty'])
def test_partial_corpus_never_passes(tmp_path,fault):
    frozen=tmp_path/'research/eval-corpus/frozen/v1';frozen.mkdir(parents=True)
    (frozen/'manifest.json').write_text('{"version":"1"}')
    (frozen/'questions.json').write_text(json.dumps([{'query':'Private test question'}]))
    if fault=='malformed':(frozen/'documents.json').write_text('{broken')
    if fault=='empty':(frozen/'documents.json').write_text('[]')
    artifact=tmp_path/'src/p8/report.md';artifact.parent.mkdir(parents=True);artifact.write_text('Clean report')
    assert run_check(tmp_path).returncode==2

@pytest.mark.parametrize('relative',['src/authority/leak.ts','README.md'])
def test_release_source_and_root_document_are_scanned(tmp_path,relative):
    frozen=tmp_path/'research/eval-corpus/frozen/v1';frozen.mkdir(parents=True)
    secret='Synthetic exact corpus body for release inventory regression.'
    (frozen/'manifest.json').write_text('{"version":"1"}')
    (frozen/'questions.json').write_text(json.dumps([{'query':'A private question?'}]))
    (frozen/'documents.json').write_text(json.dumps([{'body':secret}]))
    target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(secret)
    assert run_check(tmp_path).returncode==1
