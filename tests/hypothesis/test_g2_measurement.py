"""Execute the local retrieval measurement; do not treat it as answer-quality proof."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("measure_g2", ROOT / "src/retrieval/measure_g2.py")
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


def test_v2_load_quality_keeps_degraded_and_failed_queries():
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    from measure_perf_v2 import quality_under_load
    from build_v2 import THRESHOLDS

    questions = [
        {"id": key, "project": "main", "slice": "paraphrase", "expected": "answer", "gold": [{"page": "p"}]}
        for key in ("good", "busy", "failed")
    ]
    found = [{"project": "main", "page": "p", "resolved": True}]
    rows = [
        {"id": "good", "result": "context", "coverage": "hybrid-current", "degradation": None},
        {"id": "busy", "result": "context", "coverage": "hybrid-current", "degradation": "reranker-busy"},
        {"id": "failed", "result": "error", "coverage": None, "degradation": None},
    ]
    quality = quality_under_load(rows, questions,
                                 {"good": {"results": found}, "busy": {"results": []}, "failed": {"results": []}},
                                 THRESHOLDS)
    assert quality["all"]["evidence_recall_at_10"]["n"] == 3
    assert quality["all"]["evidence_recall_at_10"]["rate"] == 0.3333
    assert quality["groups"]["hybrid-current:reranker-busy"]["evidence_recall_at_10"]["rate"] == 0
    assert quality["groups"]["error"]["questions"] == 1


def test_measurement_uses_actual_scoped_retrieval(tmp_path):
    documents = [
        {"id": "alpha", "title": "Alpha", "body": "Alpha uses amber circuits.", "project": "a", "slice_type": "identifier_exact"},
        {"id": "hidden", "title": "Hidden", "body": "Alpha uses amber circuits.", "project": "b", "slice_type": "cross_project_lookalike"},
    ]
    questions = [{"id": "q-alpha", "query": "Alpha amber", "gold_pages": ["alpha"], "is_positive": True}]
    for name, value in (("questions.json", questions), ("documents.json", documents),
                        ("split.json", {}), ("manifest.json", {})):
        (tmp_path / name).write_text(json.dumps(value))
    report = measurement.measure(tmp_path)
    assert report["status"] == "MEASURED_NOT_A_FULL_G2_PASS"
    assert report["aggregates"]["all_positive"] == {
        "n": 1, "macro_recall_at_10": 1.0, "all_gold_pages_at_10": 1.0,
    }
    assert report["citation_count"] == 1  # other-project lookalike is not retrieved
    assert report["citation_revision_hash_body_resolution"] == 1.0
    assert report["max_returned_json_bytes"] <= 24000
    assert len(report["corpus_sha256"]["questions.json"]) == 64
    assert any("No answer-model" in limitation for limitation in report["limitations"])


def test_exact_identifier_route_is_rare_bounded_and_scoped(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "src" / "authority"))
    from authority import connect_knowledge
    import retrieval
    db = str(tmp_path / "a.db")
    a = connect_knowledge(db, "a")
    a.create_page("a", "cfg", "Config", "Set retry_budget.max_ms to 900 for the uplink.", "owner")
    a.create_page("a", "one", "One", "The fooBar flag is shared.", "owner")
    a.create_page("a", "two", "Two", "Also uses fooBar here.", "owner")
    a.create_page("a", "long", "Long", "See retry_budget.max_ms_extra for bursts.", "owner")
    connect_knowledge(db, "b").create_page("b", "leak", "Leak", "retry_budget.max_ms is 5 in project b.", "owner")
    snap = retrieval.snapshot(a, "a", "what is retry_budget.max_ms and fooBar?")
    page_of = {d["key"]: d["object"] for d in snap["documents"]}
    # unique in project a -> returned; fooBar is on two pages -> not; the longer identifier and project b never match
    assert {page_of[k] for k in snap["exact"]} == {"cfg"}
    assert retrieval.snapshot(a, "a", "plain words only")["exact"] == []
    assert retrieval.exact_identifier_keys("abc", snap["documents"]) == []  # shorter than 4 characters


def test_lexical_candidates_prioritize_subject_terms(tmp_path):
    sys.path.insert(0, str(ROOT / "src" / "authority"))
    from authority import connect_knowledge
    import retrieval

    store = connect_knowledge(str(tmp_path / "a.db"), "main")
    store.create_page("main", "subject", "Caches", "Tangerine storage retains snapshots.", "owner")
    store.create_page("main", "filler", "Questions", "Where would this be used?", "owner")
    snapshot = retrieval.snapshot(store, "main", "Where would this tangerine storage be used?")
    pages = {item["key"]: item["object"] for item in snapshot["documents"]}
    assert [pages[key] for key in snapshot["lexical"]] == ["subject"]
    fallback = retrieval.snapshot(store, "main", "Where would this be used?")
    assert [pages[key] for key in fallback["lexical"]] == ["filler"]
