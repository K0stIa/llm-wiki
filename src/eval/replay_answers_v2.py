"""Compare local answers on retrieved and exact-span development packets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import answer_v2
import measure_v2
from measure_v2 import receipts
from score_v2 import ABSTENTIONS, _valid_citation, answer_digest, rate

DIRECTORY = "answer-replay-development"
CHECKPOINT = "checkpoint.json"
RESPONSES = "responses.jsonl"
LABELS = "semantic-labels.json"
REPORT = "report.json"


@dataclass(frozen=True)
class Case:
    question: dict
    retrieved: dict
    gold_span: dict | None
    unpaired_reason: str | None = None

    @property
    def id(self) -> str:
        return self.question["id"]


def _gold_packet(db: sqlite3.Connection, question: dict, bodies: dict[str, str], coverage: str) -> dict:
    results = []
    for gold in question["gold"]:
        page, span = gold["page"], gold["span"]
        row = db.execute(
            """SELECT h.revision, r.body FROM page_heads h JOIN page_revisions r
                 ON r.revision=h.revision AND r.project=h.project AND r.page=h.page
                 WHERE h.project=? AND h.page=? AND h.state='active' AND r.state='active'""",
            (question["project"], page),
        ).fetchone()
        if not row or question["project"] != "main" or row[1] != bodies[page] or not span:
            raise ValueError
        revision, body = row
        offset = body.find(span)
        if offset < 0:
            raise ValueError
        first = body.count("\n", 0, offset) + 1
        last = body.count("\n", 0, offset + len(span)) + 1
        text = "\n".join(body.split("\n")[first - 1:last])
        passage = {"project": question["project"], "page": page, "revision": revision,
                   "hash": "h:" + hashlib.sha256(body.encode()).hexdigest(), "start": first, "end": last,
                   "resolved": True, "text": text}
        if passage not in results:
            results.append(passage)
    return {"coverage": coverage, "results": results}


def _load_cases(run: Path, raw: dict, per_slice: int | None, *, evidence_refs: bool = False) -> list[Case]:
    _, questions, split, pages, edits = measure_v2.verified_frozen()
    questions = [question for question in questions if split[question["id"]] == "development"]
    ids = {question["id"] for question in questions}
    database = run / "authority.db"
    if (not ids or len(ids) != len(questions) or ids != raw["rankings"].keys()
            or database.is_symlink() or not database.is_file()):
        raise ValueError
    sampled: Counter[str] = Counter()
    chosen = []
    for question in questions:
        slice_name = question["slice"]
        if slice_name not in measure_v2.build_v2.QUOTAS:
            raise ValueError
        if per_slice is None or sampled[slice_name] < per_slice:
            chosen.append(question)
            sampled[slice_name] += 1
    bodies = {page["id"]: page["body"] for page in pages}
    bodies.update({edit["page"]: edit["body"] for edit in edits if edit["kind"] != "lookalike"})
    rankings = measure_v2.resolve(database, {"rankings": {q["id"]: raw["rankings"][q["id"]] for q in chosen}})
    cases = []
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        for question in chosen:
            retrieved = rankings[question["id"]]
            if any(passage["project"] != question["project"] or passage["resolved"] is not True
                   for passage in retrieved["results"]):
                raise ValueError
            answer_v2._payload(question, retrieved, evidence_refs=evidence_refs)
            if question["expected"] in ABSTENTIONS:
                # Both calls exercise the independently frozen control on the same input.
                cases.append(Case(question, retrieved, retrieved))
            elif question["expected"] != "answer" or not question["gold"]:
                raise ValueError
            elif any(gold["span"] is None for gold in question["gold"]):
                cases.append(Case(question, retrieved, None, "page-only-span-unknown"))
            else:
                gold_span = _gold_packet(db, question, bodies, retrieved["coverage"])
                try:
                    answer_v2._payload(question, gold_span, evidence_refs=evidence_refs)
                except ValueError:
                    cases.append(Case(question, retrieved, None, "gold-packet-exceeds-input-budget"))
                else:
                    cases.append(Case(question, retrieved, gold_span))
    return cases


def _observation(case: Case, record: dict, label: object) -> dict:
    answer = record["answer"] if isinstance(record["answer"], dict) else {}
    status, text, refs = answer.get("status"), answer.get("answer"), answer.get("citations")
    ranking = record["ranking"]
    positive = case.question["expected"] == "answer"
    shape_ok = (status == "answer" and isinstance(text, str) and bool(text.strip())
                and isinstance(refs, list) and bool(refs))
    exact = ([_valid_citation(ref, ranking["results"], case.question["project"]) for ref in refs]
             if shape_ok else [])
    abstains = (isinstance(status, str) and status in ABSTENTIONS
                and text in (None, "") and refs in (None, []))
    wrong_reason = abstains and (
        status != "abstain-degraded" if ranking["coverage"] != "hybrid-current"
        else status == "abstain-degraded" or (not positive and status != case.question["expected"])
    )
    outcome = ("abstention" if abstains else "invalid-response" if not shape_ok
               else "answer-with-exact-quotes" if all(exact) else "answer-with-invalid-quotes")
    supports_review = (positive and outcome == "answer-with-exact-quotes")
    semantic = "ineligible"
    if supports_review:
        semantic = "pending"
        if (isinstance(label, dict) and type(label.get("correct_supported")) is bool
                and label.get("sha256") == record["sha256"]):
            semantic = "correct-supported" if label["correct_supported"] else "incorrect-or-unsupported"
    return {"outcome": outcome, "exact": exact, "wrong_reason": wrong_reason, "semantic": semantic,
            "confident": status == "answer" or text not in (None, "") or answer.get("claimed") is True,
            "abstains": abstains}


def _summary(rows: list[dict], *, positive: bool) -> dict:
    result = {
        "questions": len(rows),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "citation_resolution": rate([exact for row in rows for exact in row["exact"]]),
        "wrong_abstention_reasons": sum(row["wrong_reason"] for row in rows),
    }
    if positive:
        semantics = Counter(row["semantic"] for row in rows)
        result["false_abstentions"] = rate([row["abstains"] for row in rows])
        result["semantic_review"] = {
            "pending": semantics["pending"], "correct_supported": semantics["correct-supported"],
            "incorrect_or_unsupported": semantics["incorrect-or-unsupported"],
            "ineligible": semantics["ineligible"],
        }
    else:
        result["unsupported_confident"] = rate([row["confident"] for row in rows])
    return result


def _paired(retrieved: list[dict], gold_span: list[dict], *, positive: bool) -> dict:
    pairs = list(zip(retrieved, gold_span, strict=True))
    return {
        "retrieved": _summary(retrieved, positive=positive),
        "gold_span": _summary(gold_span, positive=positive),
        "outcome_transitions": dict(Counter(f"{a['outcome']} → {b['outcome']}" for a, b in pairs)),
        **({"semantic_transitions": dict(Counter(f"{a['semantic']} → {b['semantic']}" for a, b in pairs))}
           if positive else {}),
    }


def _report(cases: list[Case], records: dict, labels: dict) -> dict:
    positives, paired, gold = [], [], []
    controls = {}
    for case in cases:
        retrieved_id, gold_id = f"retrieved:{case.id}", f"gold_span:{case.id}"
        retrieved = _observation(case, records[retrieved_id], labels.get(retrieved_id))
        if case.question["expected"] == "answer":
            positives.append(retrieved)
            if case.gold_span is not None:
                paired.append(retrieved)
                gold.append(_observation(case, records[gold_id], labels.get(gold_id)))
        else:
            left, right = controls.setdefault(case.question["expected"], ([], []))
            left.append(retrieved)
            right.append(_observation(case, records[gold_id], labels.get(gold_id)))
    return {
        "subset": "development",
        "questions": len(cases),
        "questions_by_slice": dict(Counter(case.question["slice"] for case in cases)),
        "paired_control_packets": "identical-retrieved-context",
        "unpaired_positives": dict(Counter(case.unpaired_reason for case in cases if case.unpaired_reason)),
        "positives": {"all_retrieved": _summary(positives, positive=True),
                      "paired": _paired(paired, gold, positive=True)},
        "controls": {reason: _paired(left, right, positive=False) for reason, (left, right) in controls.items()},
    }


def replay(run: Path, *, timeout: int, max_requests: int | None, per_slice: int | None = None,
           evidence_refs: bool = False) -> dict | None:
    run = run.resolve()
    if not run.is_dir() or run.stat().st_mode & 0o077:
        raise SystemExit("answer replay requires a private retrieval run directory")
    with answer_v2._collection_lock(run):
        if any((run / name).is_symlink() for name in ("retrieval-run.json", "report.json", "raw.json")):
            raise SystemExit("answer replay requires local retrieval artifacts")
        identity, report, raw, provenance_sha = answer_v2._read_retrieval(run, resume=False)
        if report["subset"] != "development":
            raise SystemExit("answer replay accepts development retrieval runs only")
        try:
            cases = _load_cases(run, raw, per_slice, evidence_refs=evidence_refs)
        except (KeyError, ValueError, TypeError, IndexError, AttributeError, OSError, sqlite3.Error):
            raise SystemExit("could not verify development replay inputs") from None

        requests = [(f"{arm}:{case.id}", case.question, ranking)
                    for case in cases for arm, ranking in (("retrieved", case.retrieved), ("gold_span", case.gold_span))
                    if ranking is not None]
        name = DIRECTORY if per_slice is None else f"{DIRECTORY}-per-slice-{per_slice}"
        directory = run / (f"{name}-evidence-refs" if evidence_refs else name)
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise SystemExit("answer replay artifacts require a private directory")
        with answer_v2._collection_lock(directory) as dir_fd:
            return _collect(run, directory, dir_fd, cases, requests, identity, report, provenance_sha,
                            timeout, max_requests, per_slice, evidence_refs)


def _collect(run, directory, dir_fd, cases, requests, identity, retrieval, provenance_sha, timeout, max_requests,
             per_slice, evidence_refs):
    checkpoint_path, responses = directory / CHECKPOINT, directory / RESPONSES
    labels_path, report_path = directory / LABELS, directory / REPORT
    if any(path.is_symlink() for path in (checkpoint_path, responses, labels_path, report_path)):
        raise SystemExit("answer replay artifacts must be local to the private replay directory")
    checkpoint = {
        "schema": "llm-wiki/development-answer-replay/v1", "subset": "development", "identity": identity,
        "retrieval_provenance_sha256": provenance_sha, "manifest_sha256": retrieval["manifest_sha256"],
        "raw_rankings_sha256": retrieval["raw_rankings_sha256"],
        "requests_sha256": receipts.sha256_json(requests), "request_timeout_seconds": timeout, "per_slice": per_slice,
        "replay_sha256": receipts.sha256_file(Path(__file__)),
        "baseline_runner_sha256": receipts.sha256_file(Path(answer_v2.__file__)),
        "endpoint": answer_v2.ENDPOINT, "answer_profile_sha256": receipts.sha256_json(
            answer_v2._payload({"query": ""}, {"coverage": "hybrid-current", "results": []},
                               evidence_refs=evidence_refs)),
    }
    if checkpoint_path.exists():
        try:
            if json.loads(checkpoint_path.read_bytes()) != checkpoint:
                raise ValueError
        except (OSError, ValueError, RecursionError):
            raise SystemExit("answer replay checkpoint does not match the inputs or answer profile") from None
    elif responses.exists() or labels_path.exists() or report_path.exists():
        raise SystemExit("answer replay artifacts have no validated checkpoint")
    else:
        answer_v2._write_metadata(checkpoint_path, checkpoint, dir_fd)

    if not responses.exists():
        responses.touch(mode=0o600, exist_ok=False)
        os.fsync(dir_fd)
    with responses.open("r+b") as output:
        ids = [request_id for request_id, _, _ in requests]
        rankings = {request_id: ranking for request_id, _, ranking in requests}
        completed = answer_v2._verified_prefix(output, ids, rankings)
        end = len(requests) if max_requests is None else completed + max_requests
        pending = requests[completed:end]
        if pending:
            opener = answer_v2._approved_opener()
        for request_id, question, ranking in pending:
            payload = answer_v2._payload(question, ranking, evidence_refs=evidence_refs)
            if evidence_refs:
                raw, finish_reason = answer_v2._request_completion(opener, payload, timeout, completed, len(requests))
                answer = answer_v2._admit_completion(raw, finish_reason, ranking)
            else:
                raw = answer_v2._request_answer(opener, payload, timeout, completed, len(requests))
                answer = answer_v2._parse_answer(raw)
            record = {"id": request_id, "question_id": question["id"], "raw": raw, "answer": answer,
                      "ranking": ranking, "sha256": answer_digest(answer, ranking)}
            if evidence_refs:
                record["finish_reason"] = finish_reason
            record["record_sha256"] = receipts.sha256_json(record)
            output.write((json.dumps(record, ensure_ascii=False) + "\n").encode())
            output.flush()
            os.fsync(output.fileno())
            completed += 1
        if completed < len(requests):
            print(f"Retained {completed}/{len(requests)} development replay responses.")
            return None
        output.seek(0)
        records = {row["id"]: row for row in map(json.loads, output)}
    if answer_v2._read_retrieval(run, resume=False)[3] != provenance_sha:
        raise SystemExit("retrieval provenance changed during development replay")
    try:
        label_bytes = labels_path.read_bytes() if labels_path.exists() else b"{}"
        labels = json.loads(label_bytes)
        if not isinstance(labels, dict):
            raise ValueError
    except (OSError, ValueError, RecursionError):
        raise SystemExit("development replay semantic labels must be a JSON object") from None
    result = _report(cases, records, labels)
    result.update(per_slice=per_slice, checkpoint_sha256=receipts.sha256_file(checkpoint_path),
                  responses_sha256=receipts.sha256_file(responses),
                  semantic_labels_sha256=hashlib.sha256(label_bytes).hexdigest())
    answer_v2._write_metadata(report_path, result, dir_fd)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="a directory name under .cache/eval/v2/runs")
    parser.add_argument("--request-timeout-seconds", type=int, default=answer_v2.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-requests", type=int, help="limit new requests in this invocation and resume later")
    parser.add_argument("--per-slice", type=int, help="take the first N frozen development questions from every slice")
    parser.add_argument("--evidence-refs", action="store_true", help="exercise the line-reference answer profile")
    args = parser.parse_args()
    if not 1 <= args.request_timeout_seconds <= answer_v2.MAX_TIMEOUT_SECONDS:
        parser.error(f"--request-timeout-seconds must be between 1 and {answer_v2.MAX_TIMEOUT_SECONDS}")
    if args.max_requests is not None and args.max_requests < 1:
        parser.error("--max-requests must be positive")
    if args.per_slice is not None and args.per_slice < 1:
        parser.error("--per-slice must be positive")
    runs = (answer_v2.WORK / "runs").resolve()
    run = runs / args.run_id
    if run.resolve().parent != runs or run.name != args.run_id or run.is_symlink():
        parser.error("run_id must name a directory under .cache/eval/v2/runs")
    report = replay(run, timeout=args.request_timeout_seconds, max_requests=args.max_requests, per_slice=args.per_slice,
                    evidence_refs=args.evidence_refs)
    if report is not None:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
