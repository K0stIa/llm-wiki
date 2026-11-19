"""Execute the local retrieval measurement; do not treat it as answer-quality proof."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("malformed", [[], None])
def test_performance_receipt_checks_observed_profile(tmp_path, monkeypatch, capsys, malformed):
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    from measure_v2 import publish_holdout, receipts

    approved = {"device": "vulkan", "depth": 24, "docTokens": 512}
    retrieval = tmp_path / "report.json"
    provenance = tmp_path / "retrieval-run.json"
    performance = tmp_path / "performance.json"
    published = []
    monkeypatch.setattr(receipts, "approved_reranker_sha256", lambda: "approved-model")
    monkeypatch.setattr(receipts, "write_measurement", lambda *args: published.append(args) or ROOT / "receipt.json")
    settings = {"subset": "holdout", "reranker_config": approved, "reranker_sha256": "approved-model"}
    retrieval.write_text(json.dumps(settings))
    provenance.write_text(json.dumps({"report_sha256": receipts.sha256_file(retrieval),
                                      "identity": {}, "started": "synthetic"}))
    performance.write_text(json.dumps(malformed))
    publish_holdout("g2.performance", tmp_path, performance, True)
    assert "Measurement receipt withheld" in capsys.readouterr().out
    assert published == []

    for subset, measured_subset, observed, digest, count in (
        ("holdout", "holdout", {**approved, "depth": 30}, "approved-model", 0),
        ("holdout", "holdout", {**approved, "depth": 24.0}, "approved-model", 0),
        ("holdout", "holdout", approved, "wrong-model", 0),
        ("development", "development", approved, "approved-model", 0),
        ("holdout", "development", approved, "approved-model", 0),
        ("holdout", "holdout", approved, "approved-model", 1),
    ):
        retrieval.write_text(json.dumps({**settings, "subset": subset}))
        provenance.write_text(json.dumps({"report_sha256": receipts.sha256_file(retrieval),
                                          "identity": {}, "started": "synthetic"}))
        performance.write_text(json.dumps({"subset": measured_subset, "reranker_config": observed,
                                           "reranker_sha256": digest}))
        publish_holdout("g2.performance", tmp_path, performance, True)
        assert len(published) == count


@pytest.mark.parametrize("version", [1, 2])
def test_saved_trace_reports_historical_settings_and_checks_integrity(tmp_path, monkeypatch, capsys, version):
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    import trace_v2

    monkeypatch.setattr(trace_v2.build_v2, "WORK", tmp_path)
    monkeypatch.setattr(sys, "argv", ["trace_v2.py", "--run", "historical"])
    run = tmp_path / "runs" / "historical"
    run.mkdir(mode=0o700, parents=True)
    historical = {**trace_v2.approved_settings(), "depth": 30}
    assert historical != trace_v2.approved_settings()
    diagnostic = {"subset": "development"}
    outputs = set(trace_v2.OUTPUTS)
    if version == 1:
        outputs.remove("trace-questions.json")
    for name in outputs:
        (run / name).write_text("{}")
    (run / "report.json").write_text(json.dumps({"reranker_config": historical}))
    (run / "trace-report.json").write_text(json.dumps(diagnostic))
    provenance = {
        "version": version,
        "subset": "development",
        "reranker_config": historical,
        "outputs_sha256": {name: trace_v2.receipts.sha256_file(run / name) for name in outputs},
    }
    provenance_path = run / "trace-provenance.json"
    provenance_path.write_text(json.dumps(provenance))

    assert trace_v2.main() == 0
    header, body = capsys.readouterr().out.split("\n", 1)
    assert header == "run=historical"
    assert json.loads(body) == diagnostic

    mismatched = {**historical, "depth": 31}
    assert trace_v2.valid_settings(mismatched)
    provenance_path.write_text(json.dumps({**provenance, "reranker_config": mismatched}))
    with pytest.raises(SystemExit, match="recorded development provenance"):
        trace_v2.main()

    provenance_path.write_text(json.dumps({**provenance, "reranker_config": {**historical, "depth": 0}}))
    with pytest.raises(SystemExit, match="recorded development provenance"):
        trace_v2.main()

    provenance_path.write_text(json.dumps(provenance))
    (run / "trace-report.json").write_text("{}")
    with pytest.raises(SystemExit, match="recorded development provenance"):
        trace_v2.main()


def test_malformed_approved_profile_refuses_admission(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    import g2_reranker_profile

    monkeypatch.setattr(g2_reranker_profile, "__file__", str(tmp_path / "g2_reranker_profile.py"))
    profile = tmp_path / "g2-reranker-profile.json"
    profile.write_text(json.dumps({"version": 1, "settings": {"device": "vulkan", "depth": 24}}))
    with pytest.raises(ValueError, match="invalid G2 reranker profile"):
        g2_reranker_profile.approved_settings()


@pytest.mark.parametrize(("version", "depth", "tokens", "valid"), [
    (1.0, 24.0, 512.0, True),
    (True, 24, 512, False),
    (1, True, 512, False),
    (1, 24, False, False),
    (1, 24.5, 512, False),
    (1, 24, 512.5, False),
    (1, 65.0, 512, False),
    (1, 24, 31.0, False),
])
def test_profile_integer_json_numbers(tmp_path, monkeypatch, version, depth, tokens, valid):
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    import g2_reranker_profile

    monkeypatch.setattr(g2_reranker_profile, "__file__", str(tmp_path / "g2_reranker_profile.py"))
    settings = {"device": "vulkan", "depth": depth, "docTokens": tokens}
    (tmp_path / "g2-reranker-profile.json").write_text(json.dumps({"version": version, "settings": settings}))
    if valid:
        assert g2_reranker_profile.approved_settings() == settings
    else:
        with pytest.raises(ValueError, match="invalid G2 reranker profile"):
            g2_reranker_profile.approved_settings()


@pytest.mark.parametrize("observed_depth", [24, 30])
def test_development_performance_checks_retrieval_profile_before_scoring(tmp_path, monkeypatch, observed_depth):
    sys.path.insert(0, str(ROOT / "src" / "eval"))
    import measure_perf_v2 as perf

    run = tmp_path / "runs" / "fixture"
    run.mkdir(parents=True)
    model = tmp_path / "model"
    model.write_bytes(b"synthetic model")
    reranker = tmp_path / "reranker"
    reranker.write_bytes(b"synthetic reranker")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    digest = perf.receipts.sha256_file
    identity = {"commit": "fixture", "dirty": False, "model": {"sha256": digest(model)}}
    settings = {"device": "cpu", "depth": 30, "docTokens": 256}
    retrieval = {"subset": "development", "manifest_sha256": digest(manifest),
                 "reranker_sha256": digest(reranker), "reranker_config": settings}
    (run / "report.json").write_text(json.dumps(retrieval))
    (run / "retrieval-run.json").write_text(json.dumps({
        "identity": identity, "report_sha256": digest(run / "report.json"),
    }))
    (run / "questions.json").write_text("[]")
    monkeypatch.setattr(perf.build_v2, "WORK", tmp_path)
    monkeypatch.setattr(perf.build_v2, "MANIFEST", manifest)
    monkeypatch.setattr(perf.receipts, "approved_model_sha256", lambda: digest(model))
    monkeypatch.setattr(perf.receipts, "approved_reranker_sha256", lambda: digest(reranker))
    monkeypatch.setattr(perf.receipts, "current_identity", lambda **kwargs: identity)
    monkeypatch.setattr(perf, "verified_frozen", lambda: ({"thresholds": {}}, [], {}, None, None))
    monkeypatch.setenv("WIKI_TEST_CACHED_MODEL", str(model))
    monkeypatch.setenv("WIKI_EVAL_RERANKER", str(reranker))
    monkeypatch.setattr(sys, "argv", ["measure_perf_v2.py", "fixture", "--development"])

    def workload(command, **kwargs):
        assert command[-1] == "--development"
        output = run / "performance"
        output.mkdir()
        (output / "performance.json").write_text(json.dumps({
            "commit": identity["commit"], "manifest_sha256": digest(manifest),
            "script_sha256": digest(perf.ROOT / "src/eval/perf_v2.ts"),
            "reranker": {**settings, "depth": observed_depth}, "reranker_sha256": digest(reranker),
            "rows": [], "visibility": [], "service_peak_rss_bytes": 0,
            "scope": "synthetic", "sampled_process_tree_peak_rss_bytes": 0,
        }))

    scored = []
    monkeypatch.setattr(perf.subprocess, "run", workload)
    monkeypatch.setattr(perf, "score_performance", lambda *args: scored.append(True) or {"pass": True})
    monkeypatch.setattr(perf, "resolve", lambda *args: {})
    monkeypatch.setattr(perf, "quality_under_load", lambda *args: {})
    monkeypatch.setattr(perf, "publish_holdout", lambda *args: pytest.fail("development published a receipt"))
    if observed_depth == settings["depth"]:
        assert perf.main() == 0
        assert scored == [True]
    else:
        with pytest.raises(SystemExit, match="reranker settings differ from the retrieval run"):
            perf.main()
        assert not scored
