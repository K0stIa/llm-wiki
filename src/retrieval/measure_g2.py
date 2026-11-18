#!/usr/bin/env python3
"""Local-only lexical G2 measurement. Never sends corpus text to a model/provider.

Outputs aggregate scores, hashes and missing-evidence caveats, not private text.
"""
import hashlib
import importlib.util
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/authority"))
from authority import connect_knowledge
spec = importlib.util.spec_from_file_location("wiki_rpc", ROOT / "src/mcp/authority_rpc.py")
rpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpc)


def measure(corpus_dir):
    questions = json.loads((corpus_dir / "questions.json").read_text())
    documents = json.loads((corpus_dir / "documents.json").read_text())
    by_id = {d["id"]: d for d in documents}
    # v1 has no frozen per-question split assignment. Derive a reproducible,
    # explicitly new 40/60 split within each slice without altering frozen data.
    grouped = defaultdict(list)
    for question in questions:
        grouped[by_id[question["gold_pages"][0]]["slice_type"]].append(question)
    holdout = set()
    for group in grouped.values():
        ordered = sorted(group, key=lambda q: hashlib.sha256(q["id"].encode()).hexdigest())
        holdout.update(q["id"] for q in ordered[int(len(ordered) * .4):])
    scores = defaultdict(lambda: {"n": 0, "recall_sum": 0.0, "all_required": 0})
    latencies, caps, citations = [], [], []
    with tempfile.TemporaryDirectory(prefix="wiki-g2-") as tmp:
        database = str(Path(tmp) / "g2.db")
        stores = {}
        for document in documents:
            project = document["project"]
            if project not in stores:
                stores[project] = connect_knowledge(database, project)
            store = stores[project]
            store.create_page(project, document["id"], document["title"], document["body"], "local-evaluator")
        for question in questions:
            gold = question["gold_pages"]
            project = by_id[gold[0]]["project"]
            store = stores[project]
            started = time.perf_counter()
            result = rpc.lexical_recall(store, project, {"query": question["query"], "maxBytes": 24000})
            latencies.append(time.perf_counter() - started)
            caps.append(len(json.dumps(result, ensure_ascii=False).encode()))
            passages = result["evidence"]["passages"]
            found = {p["page"] for p in passages}
            for passage in passages:
                snapshot = store.page(project, passage["page"], passage["revision"])
                citations.append(snapshot.hash == passage["hash"] and
                                 "\n".join(snapshot.markdown.split("\n")[passage["start"] - 1:passage["end"]]) == passage["text"])
            if not question["is_positive"]:
                continue  # Retrieval alone cannot grade abstention or confident answers.
            slice_name = by_id[gold[0]]["slice_type"]
            split = "holdout" if question["id"] in holdout else "development"
            for key in ("all_positive", f"{split}_positive", f"{split}/{slice_name}"):
                score = scores[key]
                score["n"] += 1
                score["recall_sum"] += len(found.intersection(gold)) / len(gold)
                score["all_required"] += set(gold) <= found
    aggregates = {key: {"n": s["n"], "macro_recall_at_10": s["recall_sum"] / s["n"],
                         "all_gold_pages_at_10": s["all_required"] / s["n"]}
                  for key, s in sorted(scores.items())}
    return {
        "backend": "current-project SQLite FTS5 BM25; lexical-only",
        "status": "MEASURED_NOT_A_FULL_G2_PASS",
        "corpus_sha256": {name: hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
                          for name in ("questions.json", "documents.json", "split.json", "manifest.json")},
        "split": "new deterministic SHA256(id)-ordered 40/60 per slice; not a pre-frozen holdout",
        "aggregates": aggregates,
        "latency_p95_seconds": sorted(latencies)[int(len(latencies) * .95) - 1],
        "max_returned_json_bytes": max(caps),
        "citation_revision_hash_body_resolution": sum(citations) / len(citations) if citations else None,
        "citation_count": len(citations),
        "limitations": [
            "No answer-model correctness or abstention/confidence measurement.",
            "No QMD hybrid/vector claim. This is the runnable lexical fallback.",
            "All v1 gold lists contain one page; genuine multi-page evidence completeness cannot be established.",
            "v1 documents have one project and no supersession metadata; cross-project and historical-state claims need adversarial runtime fixtures.",
            "The split assignment is newly derived, not independently frozen before implementation.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(measure(ROOT / "research/eval-corpus/frozen/v1"), indent=2))
