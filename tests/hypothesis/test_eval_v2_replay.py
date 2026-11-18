"""Development answer replay with synthetic evidence and a local transport stub."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "eval"))
import replay_answers_v2 as replay  # noqa: E402


@pytest.fixture
def private_run(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    pages = [{"id": "p", "title": "Original", "body": "Old value"},
             {"id": "x", "title": "Distractor", "body": "Distractor secret"}]
    revised = "Other detail\nThe ✅ exact value and related fact.\nTrailing detail"
    edits = [{"kind": "supersede", "page": "p", "body": revised},
             {"kind": "lookalike", "page": "p", "body": "Cross project secret"}]
    replay.measure_v2.load_authority(run / "authority.db", pages, edits)
    questions = []
    for qid, slice_name, expected, gold in (
        ("pos", "multi_page", "answer", [{"page": "p", "span": "✅ exact value", "revision": "current"}]),
        ("page-only", "paraphrase", "answer", [{"page": "x", "span": None}]),
        ("control", "conflict_control", "abstain-conflict", [{"page": "p", "span": "✅ exact value"}]),
        ("held-out", "multi_page", "answer", [{"page": "p", "span": "✅ exact value"}]),
    ):
        questions.append({"id": qid, "project": "main", "query": f"Private question {qid}",
                          "gold": gold, "expected": expected, "slice": slice_name})
    split = {q["id"]: ("holdout" if q["id"] == "held-out" else "development") for q in questions}
    with replay.sqlite3.connect(run / "authority.db") as db:
        revision, = db.execute("SELECT revision FROM page_heads WHERE project='main' AND page='x'").fetchone()
    hit = {"page": "x", "revision": revision, "start": 1, "end": 1, "text": "Distractor secret",
           "hash": "h:" + hashlib.sha256(b"Distractor secret").hexdigest()}
    raw = {"rankings": {q["id"]: {"passages": [hit], "status": "hybrid-current", "bytes": 100, "seconds": 1}
                       for q in questions if split[q["id"]] == "development"}}
    report = {"subset": "development", "manifest_sha256": "manifest-hash",
              "raw_rankings_sha256": "rankings-hash"}
    monkeypatch.setattr(replay.answer_v2, "_read_retrieval", lambda *a, **kw: ({}, report, raw, "prov-hash"))
    monkeypatch.setattr(replay.measure_v2, "verified_frozen", lambda: ({}, questions, split, pages, edits))
    return run, pages, report, raw


def test_replay_pairs_exact_authority_and_independent_controls_and_resumes(private_run, monkeypatch, capsys):
    run, _, _, _ = private_run
    monkeypatch.setattr(replay.answer_v2, "_approved_opener", lambda: object())
    packets = []

    def request(_, payload, timeout, completed, total):
        packet = json.loads(payload["messages"][1]["content"])
        assert payload["messages"][0]["content"] == replay.answer_v2.SYSTEM
        assert timeout == 2 and completed == len(packets) and total == 5
        packets.append(packet)
        if packet["question"].endswith("control"):
            reply = ({"status": "abstain-conflict"} if len(packets) == 4
                     else {"status": "answer", "answer": "Private answer",
                           "citations": [{"passage": 1, "quote": "Invented quote"}]})
        elif packet["passages"][0]["text"].startswith("The ✅"):
            reply = {"status": "answer", "answer": "Private answer",
                     "citations": [{"passage": 1, "quote": "✅ exact value"}]}
        else:
            reply = {"status": "abstain-missing"}
        return json.dumps(reply)

    monkeypatch.setattr(replay.answer_v2, "_request_answer", request)
    assert replay.replay(run, timeout=2, max_requests=2) is None
    assert len(packets) == 2
    assert not (run / replay.DIRECTORY / replay.REPORT).exists()
    report = replay.replay(run, timeout=2, max_requests=None)
    assert packets[1]["passages"] == [{"passage": 1, "text": "The ✅ exact value and related fact."}]
    assert len(packets) == 5 and packets[3] == packets[4]
    assert all("held-out" not in p["question"] for p in packets)
    assert report["unpaired_positives"] == {"page-only-span-unknown": 1}
    assert report["positives"]["all_retrieved"]["false_abstentions"]["rate"] == 1
    assert report["positives"]["paired"]["gold_span"]["false_abstentions"]["rate"] == 0
    assert report["positives"]["paired"]["gold_span"]["semantic_review"]["pending"] == 1
    assert report["controls"]["abstain-conflict"]["retrieved"]["unsupported_confident"]["rate"] == 0
    assert report["controls"]["abstain-conflict"]["gold_span"]["unsupported_confident"]["rate"] == 1
    output = capsys.readouterr().out
    for secret in ("Private question", "exact value", "Cross project secret", "Distractor secret", "Private answer"):
        assert secret not in json.dumps(report)
        assert secret not in output

    directory = run / replay.DIRECTORY
    rows = [json.loads(line) for line in (directory / replay.RESPONSES).read_text().splitlines()]
    evidence = rows[1]["ranking"]["results"][0]
    assert evidence["project"] == "main" and evidence["start"] == evidence["end"] == 2
    (directory / replay.LABELS).write_text(json.dumps({
        rows[1]["id"]: {"sha256": rows[1]["sha256"], "correct_supported": True},
    }))
    reviewed = replay.replay(run, timeout=2, max_requests=None)
    assert len(packets) == 5
    assert reviewed["positives"]["paired"]["gold_span"]["semantic_review"]["correct_supported"] == 1


def test_holdout_or_changed_authority_cannot_reach_endpoint(private_run, monkeypatch):
    run, _, report, _ = private_run
    monkeypatch.setattr(replay.answer_v2, "_approved_opener", lambda: pytest.fail("contacted endpoint"))
    report["subset"] = "holdout"
    with pytest.raises(SystemExit, match="development"):
        replay.replay(run, timeout=2, max_requests=None)
    report["subset"] = "development"
    with replay.sqlite3.connect(run / "authority.db") as db:
        db.execute("""UPDATE page_revisions SET body=body || ' unapproved context'
                      WHERE project='main' AND page='p' AND base_revision IS NOT NULL""")
    with pytest.raises(SystemExit, match="verify development replay inputs"):
        replay.replay(run, timeout=2, max_requests=None)


def test_replay_rejects_damaged_completed_row_before_requests(private_run, monkeypatch):
    run, _, _, _ = private_run
    monkeypatch.setattr(replay.answer_v2, "_approved_opener", lambda: object())
    monkeypatch.setattr(replay.answer_v2, "_request_answer", lambda *args: '{"status":"abstain-missing"}')
    replay.replay(run, timeout=2, max_requests=1)
    responses = run / replay.DIRECTORY / replay.RESPONSES
    responses.write_bytes(responses.read_bytes().replace(b"abstain-missing", b"abstain-conflict"))
    monkeypatch.setattr(replay.answer_v2, "_approved_opener", lambda: pytest.fail("contacted endpoint"))
    with pytest.raises(SystemExit, match="damaged or mismatched"):
        replay.replay(run, timeout=2, max_requests=None)


def test_deterministic_slice_sample_includes_both_controls_and_keeps_its_own_checkpoint(private_run, monkeypatch):
    run, _, _, raw = private_run
    _, questions, split, pages, edits = replay.measure_v2.verified_frozen()
    questions.extend([
        {**questions[0], "id": "second-multi", "query": "Private question second multi"},
        {**questions[2], "id": "missing", "query": "Private question missing", "gold": [],
         "slice": "missing_control", "expected": "abstain-missing"},
    ])
    for qid in ("second-multi", "missing"):
        split[qid] = "development"
        raw["rankings"][qid] = raw["rankings"]["pos"]
    monkeypatch.setattr(replay.answer_v2, "_approved_opener", lambda: object())
    packets = []

    def request(_, payload, *args):
        packets.append(json.loads(payload["messages"][1]["content"]))
        return '{"status":"abstain-missing"}'

    monkeypatch.setattr(replay.answer_v2, "_request_answer", request)
    replay.replay(run, timeout=2, max_requests=2, per_slice=1)
    report = replay.replay(run, timeout=2, max_requests=None, per_slice=1)
    assert len(packets) == 7
    assert report["questions_by_slice"] == {"multi_page": 1, "paraphrase": 1, "conflict_control": 1,
                                            "missing_control": 1}
    assert report["unpaired_positives"] == {"page-only-span-unknown": 1}
    assert all("second multi" not in packet["question"] for packet in packets)
    assert not (run / replay.DIRECTORY).exists()
