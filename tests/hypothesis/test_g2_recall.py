"""Frozen-corpus integrity only. Measured recall lives in src/retrieval/measure_g2.py."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parents[2] / "research/eval-corpus/frozen/v1"


def load(name):
    return json.loads((CORPUS / name).read_text())


def test_frozen_file_digests():
    manifest = load("manifest.json")
    assert manifest["version"] == "1"
    for name, expected in manifest["hashes"].items():
        # The existing frozen manifest records 16-hex prefixes, not full digests.
        prefix = expected.removeprefix("c:")
        assert len(prefix) == 16
        assert hashlib.sha256((CORPUS / name).read_bytes()).hexdigest().startswith(prefix)


def test_corpus_counts_and_slice_membership():
    manifest = load("manifest.json")
    documents = load("documents.json")
    questions = load("questions.json")
    assert len(documents) == manifest["total_documents"] == 250
    assert len(questions) == manifest["total_questions"] == 250
    assert dict(Counter(d["slice_type"] for d in documents)) == manifest["stratified_counts"]
    assert len({d["id"] for d in documents}) == len(documents)
    assert len({q["id"] for q in questions}) == len(questions)
    assert sum(q["is_positive"] for q in questions) == 200


def test_questions_have_resolvable_gold_and_language():
    documents = {d["id"]: d for d in load("documents.json")}
    for question in load("questions.json"):
        assert question["query"]
        assert question["language"] in ("en", "uk")
        assert question["gold_pages"]
        assert all(page in documents for page in question["gold_pages"])
        assert all(documents[page]["body"] for page in question["gold_pages"])
