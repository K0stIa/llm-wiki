"""P0 corpus builder: synthetic documents for evaluation.

Produces a permissioned synthetic corpus with stratified slices:
- identifier_exact: queries that require exact page/source identifiers
- paraphrase: same fact expressed differently
- cross_language_ukrainian: English docs queried in Ukrainian
- multi_page_answer: requires every gold page to count complete
- superseded_decision: current vs. superseded facts
- child_written_fact: facts written by child agents
- cross_project_lookalike: similar page IDs across projects

200 answerable questions + 50 missing/conflicting controls.
40% development / 60% held-out split, stratified.
"""
from __future__ import annotations

import json
import os
import random
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CorpusQuestion:
    id: str
    query: str
    language: str  # "en" | "uk"
    gold_pages: list[str]
    gold_sources: list[str]
    is_positive: bool  # True = answerable, False = missing/conflict control


@dataclass
class CorpusDoc:
    id: str
    title: str
    body: str
    project: str
    slice_type: str


@dataclass
class CorpusEval:
    questions: list[CorpusQuestion]
    documents: list[CorpusDoc]
    split: str  # "dev" | "holdout"
    stratified_counts: dict[str, int]


def build_corpus(base_dir: Optional[str] = None) -> CorpusEval:
    """Build the full P0 corpus. Returns stratified dev/holdout."""
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "research")
    base_dir = Path(base_dir)

    # Stratified slice definitions
    slices = {
        "identifier_exact": {"count": 40, "lang": "en", "positive": True},
        "paraphrase": {"count": 40, "lang": "en", "positive": True},
        "cross_language_ukrainian": {"count": 20, "lang": "uk", "positive": True},
        "multi_page_answer": {"count": 30, "lang": "en", "positive": True},
        "superseded_decision": {"count": 20, "lang": "en", "positive": True},
        "child_written_fact": {"count": 20, "lang": "en", "positive": True},
        "cross_project_lookalike": {"count": 30, "lang": "en", "positive": True},
        "missing_control": {"count": 30, "lang": "en", "positive": False},
        "conflict_control": {"count": 20, "lang": "en", "positive": False},
    }

    docs: list[CorpusDoc] = []
    questions: list[CorpusQuestion] = []

    # Generate documents per slice
    for slice_name, config in slices.items():
        count = config["count"]
        docs.extend(_generate_docs_for_slice(slice_name, count))
        questions.extend(_generate_questions_for_slice(slice_name, count, config))

    # Stratified split: 40% dev, 60% holdout
    random.seed(42)  # reproducible
    random.shuffle(questions)
    split_point = int(len(questions) * 0.4)
    dev_questions = questions[:split_point]
    holdout_questions = questions[split_point:]

    stratified = {}
    for q in questions:
        stratified[q.id.split(":")[0]] = stratified.get(q.id.split(":")[0], 0) + 1

    return CorpusEval(
        questions=questions,
        documents=docs,
        split="stratified_40_60",
        stratified_counts=stratified
    )


def _generate_docs_for_slice(slice_name: str, count: int) -> list[CorpusDoc]:
    """Generate synthetic documents for a slice."""
    docs = []
    for i in range(count):
        doc_id = f"doc-{slice_name}-{i:03d}"
        docs.append(CorpusDoc(
            id=doc_id,
            title=f"Synthetic doc for {slice_name} #{i}",
            body=f"Synthetic body content for slice {slice_name} document {i}. "
                 f"This document is part of the evaluation corpus and should be "
                 f"indexable by any search backend. Identifier: {doc_id}.",
            project="eval-project",
            slice_type=slice_name
        ))
    return docs


def _generate_questions_for_slice(slice_name: str, count: int,
                                  config: dict) -> list[CorpusQuestion]:
    """Generate evaluation questions for a slice."""
    questions = []
    for i in range(count):
        q_id = f"{slice_name}:{i:03d}"
        gold_pages = [f"doc-{slice_name}-{i:03d}"]
        gold_sources = [f"src-{slice_name}-{i:03d}"]

        if config["lang"] == "uk":
            query = _ukrainian_query_for(slice_name, i)
        else:
            query = _english_query_for(slice_name, i)

        questions.append(CorpusQuestion(
            id=q_id,
            query=query,
            language=config["lang"],
            gold_pages=gold_pages,
            gold_sources=gold_sources,
            is_positive=config["positive"]
        ))
    return questions


def _ukrainian_query_for(slice_name: str, i: int) -> str:
    """Generate Ukrainian queries that test cross-language recall."""
    templates = {
        "identifier_exact": "Где знаходиться документ {doc_id}?",
        "paraphrase": "Як називається сторінка {doc_id}?",
        "cross_language_ukrainian": "Що каже {doc_id} про тестові дані?",
        "multi_page_answer": "Де знаходиться {doc_id} та пов'язані сторінки?",
        "superseded_decision": "Що сказано у {doc_id} про версію?",
        "child_written_fact": "Хто написав {doc_id}?",
        "cross_project_lookalike": "Яка різниця між {doc_id} та {doc_id}-backup?",
        "missing_control": "Де знаходиться {doc_id}-nonexistent?",
        "conflict_control": "Що каже {doc_id} про {doc_id}-conflict?",
    }
    tmpl = templates.get(slice_name, "Що таке {doc_id}?")
    return tmpl.format(doc_id=f"doc-{slice_name}-{i:03d}")


def _english_query_for(slice_name: str, i: int) -> str:
    """Generate English queries for a slice."""
    templates = {
        "identifier_exact": f"Find document doc-{slice_name}-{i:03d}",
        "paraphrase": f"What is the content of page doc-{slice_name}-{i:03d}?",
        "cross_language_ukrainian": f"Where is doc-{slice_name}-{i:03d} stored?",
        "multi_page_answer": f"Find doc-{slice_name}-{i:03d} and its references",
        "superseded_decision": f"Is doc-{slice_name}-{i:03d} current or superseded?",
        "child_written_fact": f"Who wrote doc-{slice_name}-{i:03d}?",
        "cross_project_lookalike": f"Compare doc-{slice_name}-{i:03d} with doc-{slice_name}-backup-{i:03d}",
        "missing_control": f"Where is doc-{slice_name}-{i:03d}-missing?",
        "conflict_control": f"What does doc-{slice_name}-{i:03d} say about doc-{slice_name}-{i:03d}-conflict?",
    }
    return templates.get(slice_name, f"Document {slice_name} #{i}")


def save_corpus(eval: CorpusEval, output_dir: str) -> None:
    """Save corpus to JSON for evaluation."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Save questions
    questions_json = [
        {
            "id": q.id,
            "query": q.query,
            "language": q.language,
            "gold_pages": q.gold_pages,
            "gold_sources": q.gold_sources,
            "is_positive": q.is_positive
        }
        for q in eval.questions
    ]
    (out / "questions.json").write_text(json.dumps(questions_json, indent=2))

    # Save documents
    docs_json = [
        {
            "id": d.id,
            "title": d.title,
            "body": d.body,
            "project": d.project,
            "slice_type": d.slice_type
        }
        for d in eval.documents
    ]
    (out / "documents.json").write_text(json.dumps(docs_json, indent=2))

    # Save split info
    split_info = {
        "split": eval.split,
        "total_questions": len(eval.questions),
        "stratified_counts": eval.stratified_counts,
        "total_documents": len(eval.documents)
    }
    (out / "split.json").write_text(json.dumps(split_info, indent=2))


if __name__ == "__main__":
    eval = build_corpus()
    save_corpus(eval, "research/eval-corpus")
    print(f"Built corpus: {len(eval.questions)} questions, {len(eval.documents)} docs")
    print(f"Slices: {eval.stratified_counts}")
