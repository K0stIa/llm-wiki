"""Eval v2 scorer and builder validators on synthetic fixtures only (no corpus text). Tier A."""
import fcntl
import hashlib
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "eval"))
import build_v2  # noqa: E402
import answer_v2  # noqa: E402
import measure_v2  # noqa: E402
import score_v2  # noqa: E402

T = build_v2.THRESHOLDS


def test_evidence_adapter_renders_exact_lf_spans_and_keeps_invalid_claims():
    from answer_evidence import admit_answer

    ranking = run([{"project": "main", "page": "p", "revision": "r", "hash": "h:fixture",
                    "start": 10, "end": 12, "text": "prefix\nточний факт 🧪\n", "resolved": True}])
    draft = {"status": "answer", "claims": [{"text": "A fact.", "evidence": [
        {"passage": 1, "firstLine": 2, "lastLine": 3},
    ]}]}
    got = admit_answer(draft, ranking)
    citation, = got["citations"]
    assert got["answer"] == "A fact."
    assert citation == {"passage": 1, "quote": "точний факт 🧪\n", "revision": "r",
                        "hash": "h:fixture", "start": 11, "end": 12}

    for first, last in [(True, 2), (0, 2), (1, 4), (3, 2)]:
        draft["claims"][0]["evidence"][0].update(firstLine=first, lastLine=last)
        rejected = admit_answer(draft, ranking)
        assert rejected == {"status": "invalid-draft", "claimed": True}
        control = q("control", "missing_control", [], expected="abstain-missing")
        report = score_v2.score_answers([control], {"control": "holdout"}, {"control": ranking},
                                        {"control": rejected}, {}, T)
        assert report["invalid_responses"] == 1
        assert report["unsupported_confident_on_controls"]["rate"] == 1

    assert admit_answer({"status": "abstain-conflict"}, ranking) == {"status": "abstain-conflict"}
    assert admit_answer({"status": "abstain-missing", "answer": "fabricated"}, ranking) == {
        "status": "invalid-draft", "claimed": True,
    }


def test_performance_scores_measured_overlap_exact_visibility_and_frozen_limits():
    rows = [{"reader": reader, "step": step, "start": 0, "end": 8000,
             "seconds": 8, "result": "context", "coverage": "hybrid-stale"}
            for reader in range(10) for step in range(10)]
    publications = [{"commit_at": 1, "seconds": 30, "exact": True} for _ in range(10)]
    report = score_v2.score_performance(rows, publications, T["rss_max_bytes"], T)
    assert report["pass"]
    assert report["coverage"] == {"hybrid-stale": 100}

    publications[-1] = {"commit_at": 1, "seconds": 31, "exact": False}
    report = score_v2.score_performance(rows, publications, T["rss_max_bytes"] + 1, T)
    assert report["checks"] == {
        "workload": True, "context": True, "overlap": True, "warm_recall_p95": True,
        "visibility_p95": False, "exact_visibility": False, "service_rss": False,
    }
    assert not report["pass"]
    assert not score_v2.score_performance(rows[:-1], publications, 1, T)["checks"]["workload"]
    assert not score_v2.score_performance(rows, [{"commit_at": 8001, "seconds": 30, "exact": True}] * 10, 1, T)["checks"]["overlap"]


def q(qid, slice_name, gold, expected="answer", project="main", **extra):
    return {"id": qid, "slice": slice_name, "project": project, "expected": expected,
            "gold": [{"page": g, "span": "x"} for g in gold], **extra}


def hit(page, project="main", resolved=True, text=""):
    return {"project": project, "page": page, "revision": "r", "resolved": resolved, "text": text}


def run(results, nbytes=1000):
    return {"results": results, "coverage": "hybrid-current", "bytes": nbytes}


def test_recall_is_macro_over_questions_and_counts_only_top_10():
    questions = [q("a", "paraphrase", ["p1"]), q("b", "multi_page", ["p2", "p3"]), q("c", "paraphrase", ["p9"])]
    split = {"a": "holdout", "b": "holdout", "c": "holdout"}
    rankings = {"a": run([hit("p1")]), "b": run([hit("p2")]),
                "c": run([hit(f"x{i}") for i in range(10)] + [hit("p9")])}  # 11th result ignored
    r = score_v2.score_retrieval(questions, split, rankings, T)
    assert r["evidence_recall_at_10"]["rate"] == round((1 + 0.5 + 0) / 3, 4)
    assert r["all_evidence_at_10_multi_page"]["rate"] == 0.0
    assert r["slice_recall_at_10"]["paraphrase"]["n"] == 2


def test_only_requested_subset_is_scored_and_missing_rankings_fail():
    questions = [q("a", "paraphrase", ["p1"]), q("b", "paraphrase", ["p1"])]
    split = {"a": "development", "b": "holdout"}
    r = score_v2.score_retrieval(questions, split, {"b": run([hit("p1")])}, T)
    assert r["questions"] == 1
    with pytest.raises(ValueError):
        score_v2.score_retrieval(questions, {"a": "holdout", "b": "holdout"}, {"b": run([])}, T)


def test_cross_project_hits_count_as_disclosure_not_recall():
    questions = [q("a", "cross_project_lookalike", ["p1"])]
    r = score_v2.score_retrieval(questions, {"a": "holdout"}, {"a": run([hit("p1", project="lookalike")])}, T)
    assert r["cross_project_disclosures"] == 1
    assert r["evidence_recall_at_10"]["rate"] == 0.0
    assert r["checks"]["cross_project_disclosures"] is False


def test_unresolved_citation_and_superseded_text_fail_their_gates():
    questions = [q("a", "superseded_decision", ["p1"], superseded_span="OLD VALUE 7")]
    rankings = {"a": run([hit("p1", text="still says OLD VALUE 7 here"), hit("p2", resolved=False)])}
    r = score_v2.score_retrieval(questions, {"a": "holdout"}, rankings, T)
    assert r["superseded_as_current"] == 1 and r["checks"]["superseded_as_current"] is False
    assert r["citation_resolution"]["rate"] == 0.5 and r["checks"]["citation_resolution"] is False


def test_controls_do_not_count_toward_recall_but_are_checked_for_disclosure():
    questions = [q("a", "missing_control", [], expected="abstain-missing"), q("b", "paraphrase", ["p1"])]
    rankings = {"a": run([hit("z", project="other")]), "b": run([hit("p1")])}
    r = score_v2.score_retrieval(questions, {"a": "holdout", "b": "holdout"}, rankings, T)
    assert r["evidence_recall_at_10"]["n"] == 1 and r["cross_project_disclosures"] == 1


def test_byte_cap_and_holdout_size_gates():
    questions = [q(f"q{i}", "paraphrase", ["p"]) for i in range(30)]
    split = {x["id"]: "holdout" for x in questions}
    rankings = {x["id"]: run([hit("p")], nbytes=24001) for x in questions}
    r = score_v2.score_retrieval(questions, split, rankings, T)
    assert r["checks"]["context_bytes"] is False
    assert r["checks"]["holdout_size.paraphrase"] is True
    assert r["checks"]["holdout_size.multi_page"] is False
    assert r["pass"] is False


def test_wilson_interval_is_bounded_and_sensible():
    assert score_v2.wilson(0, 0) is None
    lo, hi = score_v2.wilson(29, 30)
    assert 0.8 < lo < 0.97 < hi <= 1.0
    assert score_v2.wilson(30, 30)[1] == 1.0


def test_builder_helpers():
    assert build_v2.cyrillic_share("Як налаштувати kv cache?") > 0.6
    assert build_v2.cyrillic_share("How to configure kv cache?") == 0
    assert "configure" in build_v2.content_words("How to configure the cache")
    assert "the" not in build_v2.content_words("the the the")
    assert build_v2.order_key("a", "b") == build_v2.order_key("a", "b") != build_v2.order_key("b", "a")


def test_quotas_keep_30_holdout_per_hard_slice():
    for s in score_v2.HARD:
        quota = build_v2.QUOTAS[s]
        assert quota - round(0.4 * quota) >= 30, s


def test_thresholds_match_decisions_record():
    text = (ROOT / "specs" / "wiki-system" / "DECISIONS.md").read_text()
    for marker in ("≥ 95%", "≥ 90%", "100%", "≤ 5%", "≤ 2 s", "≤ 30 s", "≤ 2 GiB", "24,000"):
        assert marker in text
    assert T["evidence_recall_at_10"] == 0.95 and T["answers_correct_supported"] == 0.90
    assert T["unsupported_confident_on_controls_max"] == 0.05 and T["warm_recall_p95_seconds"] == 8.0


def test_answer_scoring_requires_exact_citations_and_bound_semantic_review():
    questions = [q("a", "multi_page", ["p1", "p2"]), q("b", "missing_control", [], expected="abstain-missing")]
    split = {item["id"]: "holdout" for item in questions}
    evidence = {qid: run([hit("p1", text="first fact"), hit("p2", text="second fact")]) for qid in split}
    answers = {"a": {"status": "answer", "answer": "Both facts.", "citations": [
        {"passage": 1, "quote": "first fact"}, {"passage": 2, "quote": "second fact"}]},
        "b": {"status": "abstain-missing"}}
    labels = {"a": {"sha256": score_v2.answer_digest(answers["a"], evidence["a"]), "correct_supported": True}}
    report = score_v2.score_answers(questions, split, evidence, answers, labels, T)
    assert report["pass"] is True
    assert report["answers_correct_supported"]["rate"] == 1

    evidence["a"]["results"][1]["project"] = "other"
    labels["a"]["sha256"] = score_v2.answer_digest(answers["a"], evidence["a"])
    report = score_v2.score_answers(questions, split, evidence, answers, labels, T)
    assert report["pass"] is False
    assert report["citation_resolution"]["rate"] == 0.5

    evidence["a"]["results"][1]["project"] = "main"
    report = score_v2.score_answers(questions, split, evidence, answers, labels, T)
    assert report["pending_semantic_reviews"] == 1
    assert report["pass"] is False


@pytest.mark.parametrize("response, coverage, invalid, wrong_abstention, unsupported", [
    ({"status": "abstain-conflict"}, "hybrid-current", 0, 1, 0),
    ({"status": "abstain-degraded"}, "not-current", 0, 0, 0),
    ({"status": "abstain-degraded"}, "hybrid-current", 0, 1, 0),
    ({"status": "answer", "answer": "Claim", "citations": []}, "hybrid-current", 1, 0, 1),
    (None, "hybrid-current", 1, 0, 0),
])
def test_answer_scoring_distinguishes_unsupported_answers_and_abstentions(
        response, coverage, invalid, wrong_abstention, unsupported):
    question = q("control", "missing_control", [], expected="abstain-missing")
    report = score_v2.score_answers([question], {"control": "holdout"},
                                    {"control": {**run([]), "coverage": coverage}},
                                    {"control": response}, {}, T)
    assert report["invalid_responses"] == invalid
    assert report["wrong_abstentions"] == wrong_abstention
    assert report["unsupported_confident_on_controls"]["rate"] == unsupported
    assert report["pass"] is False  # A control-only run cannot satisfy the positive threshold.


@pytest.fixture
def answer_run(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "example"
    run_dir.mkdir(parents=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"thresholds": T}))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    questions = [q("a", "paraphrase", ["p1"], query="How?"),
                 q("b", "missing_control", [], expected="abstain-missing", query="Where?")]
    split = {item["id"]: "development" for item in questions}
    identity = {"commit": "b" * 40, "dirty": False, "model": {"sha256": "a" * 64}}
    db = run_dir / "authority.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE page_revisions(revision TEXT, page TEXT, project TEXT, body TEXT)")
        conn.execute("INSERT INTO page_revisions VALUES ('r', 'p1', 'main', 'first fact')")
    passage = {"page": "p1", "revision": "r", "start": 1, "end": 1, "text": "first fact",
               "hash": "h:" + hashlib.sha256(b"first fact").hexdigest()}
    ranking = {"coverage": "hybrid-current", "status": "ok", "bytes": 1000, "seconds": 0.4}
    raw = {"rankings": {"a": {**ranking, "passages": [passage]}, "b": {**ranking, "passages": []}}}
    (run_dir / "raw.json").write_text(json.dumps(raw))
    evidence = {
        "a": {**run([{"project": "main", "resolved": True, **passage}]), "seconds": 0.4},
        "b": {**run([]), "seconds": 0.4},
    }
    report = {"subset": "development", "manifest_sha256": digest,
              "model_sha256": identity["model"]["sha256"],
              "raw_rankings_sha256": hashlib.sha256((run_dir / "raw.json").read_bytes()).hexdigest()}
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report))
    (run_dir / "retrieval-run.json").write_text(json.dumps({
        "identity": identity, "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }))
    monkeypatch.setattr(answer_v2, "WORK", tmp_path)
    monkeypatch.setattr(answer_v2, "MANIFEST", manifest)
    monkeypatch.setattr(measure_v2, "verified_frozen", lambda: ({"thresholds": T}, questions, split, [], []))
    monkeypatch.setattr(measure_v2.receipts, "current_identity", lambda **_: identity.copy())
    monkeypatch.setattr(measure_v2.receipts, "approved_model_sha256", lambda: identity["model"]["sha256"])
    monkeypatch.setattr(measure_v2, "publish_holdout", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["answer_v2.py", "example"])
    return run_dir, questions, evidence, report, identity


def test_answer_run_round_trip_uses_only_supplied_passages(answer_run, monkeypatch, capsys):
    run_dir, questions, evidence, report, identity = answer_run
    responses = iter([{"status": "answer", "answer": "First fact.", "citations": [
        {"passage": 1, "quote": "first fact"}]}, {"status": "abstain-missing"}])
    transmitted = []

    class LocalEndpoint:
        def open(self, request, *, timeout):
            if isinstance(request, str):
                assert request == answer_v2.ENDPOINT.removesuffix("/chat/completions") + "/models"
                value = {"data": [{"id": answer_v2.MODEL}]}
            else:
                assert request.full_url == answer_v2.ENDPOINT
                payload = json.loads(request.data)
                transmitted.append(json.loads(payload["messages"][1]["content"]))
                value = {"choices": [{"message": {"content": json.dumps(next(responses))}}]}
            return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(answer_v2.urllib.request, "build_opener", lambda *_: LocalEndpoint())
    answer_v2.collect(run_dir, questions, evidence, report, identity)
    assert transmitted[0] == {"question": "How?", "coverage": "hybrid-current",
                              "passages": [{"passage": 1, "text": "first fact"}]}
    assert answer_v2.main() == 1
    records = [json.loads(line) for line in (run_dir / "answers.jsonl").read_text().splitlines()]
    (run_dir / "answer-labels.json").write_text(json.dumps({
        "a": {"sha256": records[0]["sha256"], "correct_supported": True},
    }))
    assert answer_v2.main() == 0
    assert "first fact" not in capsys.readouterr().out.lower()
    with (run_dir / "answers.jsonl").open("a") as raw:
        raw.write("{}\n")
    with pytest.raises(SystemExit, match="do not match"):
        answer_v2.main()


def test_answer_collection_resumes_after_timeout_and_torn_line(answer_run, monkeypatch, capsys):
    run_dir, *_ = answer_run
    transmitted = []

    class LocalEndpoint:
        def open(self, request, *, timeout):
            if isinstance(request, str):
                value = {"data": [{"id": answer_v2.MODEL}]}
            else:
                assert request.full_url == answer_v2.ENDPOINT
                payload = json.loads(request.data)
                transmitted.append((json.loads(payload["messages"][1]["content"])["question"], timeout))
                if len(transmitted) == 2:
                    raise TimeoutError("First fact")
                value = {"choices": [{"message": {"content": '{"status":"abstain-missing"}'}}]}
            return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(answer_v2.urllib.request, "build_opener", lambda *_: LocalEndpoint())
    monkeypatch.setattr(sys, "argv", ["answer_v2.py", "example", "--resume", "--request-timeout-seconds", "180"])
    with pytest.raises(SystemExit, match="timed out") as exc:
        answer_v2.main()
    assert "First fact" not in str(exc.value)
    assert "1/2" in str(exc.value)
    assert not (run_dir / "answer-run.json").exists()
    responses = run_dir / "answers.jsonl"
    first_row = responses.read_bytes()
    assert json.loads(first_row)["id"] == "a"
    responses.write_bytes(first_row + b'{"unfinished":')

    assert answer_v2.main() == 0
    assert transmitted == [("How?", 180), ("Where?", 180), ("Where?", 180)]
    assert responses.read_bytes().startswith(first_row)
    assert [json.loads(line)["id"] for line in responses.read_bytes().splitlines()] == ["a", "b"]
    assert json.loads((run_dir / "answer-run.json").read_bytes())["request_timeout_seconds"] == 180
    assert "First fact" not in capsys.readouterr().out


def test_answer_resume_rejects_an_altered_complete_row(answer_run, monkeypatch):
    run_dir, *_ = answer_run
    responses = iter(['{"status":"abstain-missing"}'])

    class LocalEndpoint:
        def open(self, request, *, timeout):
            if isinstance(request, str):
                value = {"data": [{"id": answer_v2.MODEL}]}
            else:
                raw = next(responses, None)
                if raw is None:
                    raise TimeoutError
                value = {"choices": [{"message": {"content": raw}}]}
            return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(answer_v2.urllib.request, "build_opener", lambda *_: LocalEndpoint())
    monkeypatch.setattr(sys, "argv", ["answer_v2.py", "example", "--resume"])
    with pytest.raises(SystemExit, match="timed out"):
        answer_v2.main()
    responses_file = run_dir / "answers.jsonl"
    record = json.loads(responses_file.read_text())
    record["raw"] += " "  # The parsed answer would still be identical.
    modified = json.dumps(record) + "\n"
    responses_file.write_text(modified)

    def no_network(*_):
        pytest.fail("altered answer reached the endpoint")

    monkeypatch.setattr(answer_v2.urllib.request, "build_opener", no_network)
    with pytest.raises(SystemExit, match="mismatched completed row"):
        answer_v2.main()
    assert responses_file.read_text() == modified
    assert not (run_dir / "answer-run.json").exists()


@pytest.mark.parametrize("invalid", ["stale", "raw checksum", "legacy", "lock", "deadline"])
def test_answer_resume_rejects_unverified_inputs_before_network(answer_run, monkeypatch, invalid):
    run_dir, *_ = answer_run
    flags = []
    if invalid == "stale":
        monkeypatch.setattr(measure_v2.receipts, "current_identity", lambda **_: {"commit": "c" * 40})
    elif invalid == "raw checksum":
        (run_dir / "raw.json").write_text("{}")
    elif invalid == "legacy":
        (run_dir / "answers.jsonl").write_text("{}\n")
    elif invalid == "deadline":
        flags = ["--request-timeout-seconds", "301"]

    def no_network(*_):
        pytest.fail("unverified inputs reached the endpoint")

    monkeypatch.setattr(answer_v2.urllib.request, "build_opener", no_network)
    monkeypatch.setattr(sys, "argv", ["answer_v2.py", "example", "--resume", *flags])
    fd = os.open(run_dir, os.O_RDONLY)
    try:
        if invalid == "lock":
            fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(SystemExit) as exc:
            answer_v2.main()
        if invalid == "deadline":
            assert exc.value.code == 2
        else:
            assert isinstance(exc.value.code, str)
    finally:
        os.close(fd)


class _Gen:
    def __init__(self, pages):
        self.pages = pages
        self.by_id = {p["id"]: p for p in pages}
        self.all_norm = [build_v2.norm(p["body"]) for p in pages]


def test_related_pages_rank_by_rare_overlap_and_exclude():
    pages = [{"id": "a", "title": "kv cache", "body": "quantization of kv cache in llama server"},
             {"id": "b", "title": "notes", "body": "server notes about cache"},
             {"id": "c", "title": "other", "body": "unrelated gardening text"}]
    gen = _Gen(pages)
    got = [p["id"] for p in build_v2.related_pages(gen, "kv cache quantization", exclude=set())]
    assert got[0] == "a" and "c" not in got
    assert "a" not in [p["id"] for p in build_v2.related_pages(gen, "kv cache quantization", exclude={"a"})]


def test_clip_keeps_short_bodies_and_best_paragraphs_of_long_ones():
    assert build_v2.clip("short body", "x") == "short body"
    long = "\n\n".join(["filler words here " * 40] * 20 + ["the answer mentions quantization here"])
    out = build_v2.clip(long, "quantization", limit=2000)
    assert "quantization" in out and len(out) <= 2000 + 200


def test_label_context_includes_synthetic_edits_and_related_pages_for_controls():
    pages = [{"id": "a", "title": "kv cache", "body": "kv cache quantization setting is q8"},
             {"id": "b", "title": "kv", "body": "kv cache quantization notes"}]
    gen = _Gen(pages)
    q = {"slice": "conflict_control", "query": "kv cache quantization?", "pages_used": ["a"], "gold": [{"page": "a", "span": "q8"}],
         "edits": [{"page": "conflict-1", "title": "t", "body": "kv cache quantization is q4"}]}
    shown, cands = build_v2.label_context(gen, q)
    assert [p["id"] for p in shown] == ["a", "conflict-1"] and [p["id"] for p in cands] == ["b"]


def test_labeling_page_records_label_source():
    html = (ROOT / "src" / "eval" / "labeling.html").read_text()
    assert "i.suggestion.verified" in html and "source: 'owner'" in html and "source: 'suggestion-confirmed'" in html and "/*ITEMS*/[]" in html
    assert "http" not in html.replace("http-equiv", "")  # no network requests from the local page


def test_missing_control_reject_needs_a_verbatim_quote():
    pages = {"a": {"id": "a", "title": "t", "body": "The server listens on port 8080 by default."}}
    good = build_v2.missing_verdict({"answered": True, "page": "a", "quote": "listens on port 8080 by default"}, pages)
    assert good["verdict"] == "reject" and good["verified"] is True
    made_up = build_v2.missing_verdict({"answered": True, "page": "a", "quote": "listens on port 9090 by default"}, pages)
    assert made_up["verdict"] is None and made_up["verified"] is False
    wrong_page = build_v2.missing_verdict({"answered": True, "page": "zz", "quote": "listens on port 8080 by default"}, pages)
    assert wrong_page["verdict"] is None
    assert build_v2.missing_verdict({"answered": False, "natural": True}, pages) == {**build_v2.missing_verdict({"answered": False}, pages)}
    assert build_v2.missing_verdict({"answered": False}, pages)["verdict"] == "accept"
    unnatural = build_v2.missing_verdict({"answered": False, "natural": False}, pages)
    assert unnatural["verdict"] == "reject" and unnatural["verified"] is False
    assert build_v2.missing_verdict(None, pages)["verdict"] is None


def test_interpret_keeps_only_shown_candidates_as_extra_gold():
    shown = [{"id": "a", "title": "t", "body": "b"}]
    cands = [{"id": "c1", "title": "t", "body": "b"}]
    r = build_v2.interpret("positive", {"verdict": "accept", "also_answering": ["c1", "invented"]}, shown, cands)
    assert r["verdict"] == "accept-with-gold" and r["extra_gold"] == ["c1"]
    assert build_v2.interpret("conflict_control", {"verdict": "maybe"}, shown, cands)["verdict"] is None
    assert set(build_v2.CODEX_SCHEMAS) == {"missing_control", "conflict_control", "positive"}


def test_fulfil_serves_pages_searches_and_phrases_from_local_corpus_only():
    pages = [{"id": "a", "title": "kv cache", "body": "kv cache quantization uses q8 on the server"},
             {"id": "b", "title": "other", "body": "gardening notes"}]
    gen = _Gen(pages)
    synthetic = {"conflict-1": {"id": "conflict-1", "title": "c", "body": "kv cache quantization uses q4"}}
    text, served, counts = build_v2.fulfil(gen, [{"kind": "page", "value": "conflict-1"}, {"kind": "search", "value": "kv quantization"},
                                                 {"kind": "phrase", "value": "uses q8"}, {"kind": "page", "value": "missing"},
                                                 {"kind": "shell", "value": "rm -rf /"}], synthetic)
    ids = [p["id"] for p in served]
    assert ids[0] == "conflict-1" and "a" in ids and "b" not in ids
    assert counts["page:empty"] == 1 and "shell" not in "".join(counts)


def test_supersede_edit_must_remove_old_text():
    body = "port is 8080 and later 8080"
    assert build_v2.edit_ok("superseded_decision", "port is 8080", "port is 9090", body.replace("port is 8080", "port is 9090", 1))
    # replacement re-forms the old text at the boundary
    assert not build_v2.edit_ok("superseded_decision", "is 80", "is 8", "port is 8" + "0")
    assert build_v2.edit_ok("cross_project_lookalike", "a", "b", "a")
    q = {"slice": "superseded_decision", "superseded_span": "old value", "edits": [{"kind": "supersede", "body": "still old value"}]}
    assert not build_v2.item_still_valid(q)
    # the old span must not survive anywhere else in the current corpus either
    q = {"slice": "superseded_decision", "superseded_span": "old value", "edits": [{"kind": "supersede", "page": "p", "body": "new value"}]}
    assert build_v2.item_still_valid(q, ["unrelated"]) and not build_v2.item_still_valid(q, ["has the old value too"])
    bodies = build_v2.current_bodies([{"id": "p", "body": "old value"}, {"id": "o", "body": "x"}], [q])
    assert bodies[("main", "p")] == "new value"


def test_superseded_validity_settles_after_drops():
    pages = [{"id": "p", "body": "alpha old value"}, {"id": "r", "body": "beta second old"}]
    # q1 removes "alpha old value"; q2 removes "second old" from r but its new body re-introduces q1's old span.
    q1 = {"id": "1", "slice": "superseded_decision", "superseded_span": "alpha old value",
          "edits": [{"kind": "supersede", "page": "p", "body": "alpha new value"}]}
    q2 = {"id": "2", "slice": "superseded_decision", "superseded_span": "second old",
          "edits": [{"kind": "supersede", "page": "r", "body": "beta alpha old value"}]}
    keep, dropped = build_v2.settle_valid(pages, [q1, q2])
    assert [q["id"] for q in dropped] == ["1"] and [q["id"] for q in keep] == ["2"]
    # Cascade: q3 is invalid (its span is on page b); dropping it restores page a's original body,
    # which contains q4's old span, so a second round must drop q4 too.
    pages = [{"id": "a", "body": "aaa first old and ccc gone text"}, {"id": "b", "body": "bbb aaa first old"},
             {"id": "c", "body": "ccc gone text here"}]
    q3 = {"id": "3", "slice": "superseded_decision", "superseded_span": "aaa first old",
          "edits": [{"kind": "supersede", "page": "a", "body": "aaa first new"}]}
    q4 = {"id": "4", "slice": "superseded_decision", "superseded_span": "ccc gone text",
          "edits": [{"kind": "supersede", "page": "c", "body": "ccc new here"}]}
    assert build_v2.item_valid_in(q4, build_v2.current_bodies(pages, [q3, q4]))  # valid in round one
    keep, dropped = build_v2.settle_valid(pages, [q3, q4])
    assert [q["id"] for q in dropped] == ["3", "4"] and keep == []
    # an overwritten own edit is invalid even if the span is gone
    q5 = {"id": "5", "slice": "superseded_decision", "superseded_span": "bb shared phrase",
          "edits": [{"kind": "supersede", "page": "b", "body": "bb fresh"}]}
    q6 = {"id": "6", "slice": "child_written_fact", "edits": [{"kind": "child", "page": "b", "body": "bb other"}]}
    keep, dropped = build_v2.settle_valid(pages[:2], [q5, q6])
    assert [q["id"] for q in dropped] == ["5"]


def test_lookalike_ambiguity_uses_short_span_threshold():
    from types import SimpleNamespace
    gen = SimpleNamespace(pages=[{"id": "gold"}, {"id": "other"}], all_norm=["port is 8080 here", "the port is 8080 too"])
    elsewhere = build_v2.Generator.elsewhere
    assert not elsewhere(gen, "port is 8080", ["gold"])  # 12 chars: below the default 20
    assert elsewhere(gen, "port is 8080", ["gold"], build_v2.LOOKALIKE_MIN_SPAN)
    assert not elsewhere(gen, "port is 8080", ["gold", "other"], build_v2.LOOKALIKE_MIN_SPAN)
