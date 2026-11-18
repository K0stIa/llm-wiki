"""Pure scoring for eval v2 retrieval and answer runs (Tier A tested).

score_retrieval(questions, split, rankings, thresholds) -> report

rankings[qid] = {"results": [{"project", "page", "revision", "resolved": bool, "text": str}, ...],
                 "coverage": str, "bytes": int}
Only the first 10 results count. The report contains counts, rates and
Wilson 95% intervals: no question text, so it is safe to print.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict

HARD = ("paraphrase", "cross_language_ukrainian", "multi_page", "superseded_decision",
        "cross_project_lookalike", "child_written_fact")
ABSTENTIONS = {"abstain-missing", "abstain-conflict", "abstain-degraded"}


def wilson(successes: float, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rate(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n if n else None
    return {"n": n, "rate": None if mean is None else round(mean, 4), "ci95": wilson(sum(values), n)}


def score_retrieval(questions: list[dict], split: dict, rankings: dict, thresholds: dict,
                    subset: str = "holdout") -> dict:
    chosen = [q for q in questions if split.get(q["id"]) == subset]
    missing = [q["id"] for q in chosen if q["id"] not in rankings]
    if missing:
        raise ValueError(f"{len(missing)} questions have no ranking; a run must cover the whole subset")
    recall, all_evidence, by_slice = [], [], defaultdict(list)
    disclosures = superseded_current = unresolved = total_results = 0
    max_bytes = 0
    for q in chosen:
        r = rankings[q["id"]]
        top = r["results"][:10]
        max_bytes = max(max_bytes, r.get("bytes", 0))
        for item in top:
            total_results += 1
            unresolved += 0 if item.get("resolved") else 1
            if item.get("project") != q["project"]:
                disclosures += 1
        superseded = q.get("superseded_span")
        if superseded and any(superseded in (item.get("text") or "") for item in top):
            superseded_current += 1
        if q["expected"] != "answer":
            continue
        gold_pages = {g["page"] for g in q["gold"]}
        found = {item["page"] for item in top if item.get("project") == q["project"] and item.get("resolved")}
        per_question = len(gold_pages & found) / len(gold_pages)
        recall.append(per_question)
        by_slice[q["slice"]].append(per_question)
        if q["slice"] == "multi_page":
            all_evidence.append(1.0 if gold_pages <= found else 0.0)
    report = {
        "subset": subset, "questions": len(chosen),
        "evidence_recall_at_10": rate(recall),
        "all_evidence_at_10_multi_page": rate(all_evidence),
        "slice_recall_at_10": {s: rate(v) for s, v in sorted(by_slice.items())},
        "citation_resolution": rate([0.0] * unresolved + [1.0] * (total_results - unresolved)),
        "cross_project_disclosures": disclosures,
        "superseded_as_current": superseded_current,
        "max_context_bytes": max_bytes,
    }
    hard_min = thresholds["hard_slice_recall_at_10"]
    checks = {
        "evidence_recall_at_10": (report["evidence_recall_at_10"]["rate"] or 0) >= thresholds["evidence_recall_at_10"],
        "all_evidence_at_10_multi_page": (report["all_evidence_at_10_multi_page"]["rate"] or 0) >= thresholds["all_evidence_at_10_multi_page"],
        **{f"slice_recall_at_10.{s}": ((report["slice_recall_at_10"].get(s) or {}).get("rate") or 0) >= t for s, t in hard_min.items()},
        "citation_resolution": report["citation_resolution"]["rate"] == thresholds["citation_resolution"],
        "cross_project_disclosures": disclosures <= thresholds["cross_project_disclosures"],
        "superseded_as_current": superseded_current <= thresholds["superseded_as_current"],
        "context_bytes": max_bytes <= thresholds["context_bytes_max"],
    }
    for s in HARD:  # every measured hard slice needs >= 30 held-out positives (DELIVERY G0)
        if subset == "holdout":
            checks[f"holdout_size.{s}"] = len(by_slice.get(s, [])) >= 30
    report["checks"] = checks
    report["pass"] = all(checks.values())
    return report


def answer_digest(answer: object, ranking: dict) -> str:
    evidence = {"coverage": ranking["coverage"], "results": ranking["results"]}
    value = json.dumps([answer, evidence], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def _valid_citation(citation: object, passages: list, project: str) -> bool:
    if not isinstance(citation, dict):
        return False
    index, quote = citation.get("passage"), citation.get("quote")
    if type(index) is not int or not 1 <= index <= len(passages) or not isinstance(quote, str) or not quote.strip():
        return False
    passage = passages[index - 1]
    return passage["project"] == project and passage["resolved"] is True and quote in passage["text"]


def score_answers(questions: list[dict], split: dict, rankings: dict, answers: dict, labels: dict,
                  thresholds: dict, subset: str = "holdout") -> dict:
    chosen = [q for q in questions if split.get(q["id"]) == subset]
    if any(q["id"] not in rankings or q["id"] not in answers for q in chosen):
        raise ValueError("an answer run must cover the entire requested subset")
    positives, controls, citations = [], [], []
    invalid = wrong_abstentions = pending = 0
    for question in chosen:
        qid = question["id"]
        answer, ranking = answers[qid], rankings[qid]
        answer = answer if isinstance(answer, dict) else {}
        status = answer.get("status")
        is_positive = question["expected"] == "answer"
        correct = False
        if status == "answer":
            text, refs = answer.get("answer"), answer.get("citations")
            valid = isinstance(text, str) and bool(text.strip()) and isinstance(refs, list) and bool(refs)
            invalid += not valid
            if valid:
                exact = [_valid_citation(ref, ranking["results"], question["project"]) for ref in refs]
                citations.extend(exact)
                if is_positive and all(exact) and ranking["coverage"] == "hybrid-current":
                    label = labels.get(qid)
                    if (isinstance(label, dict) and type(label.get("correct_supported")) is bool
                            and label.get("sha256") == answer_digest(answer, ranking)):
                        correct = label["correct_supported"]
                    else:
                        pending += 1
        elif isinstance(status, str) and status in ABSTENTIONS:
            has_claim = (answer.get("answer") not in (None, "") or answer.get("citations") not in (None, []))
            invalid += has_claim
            if ranking["coverage"] != "hybrid-current":
                wrong_abstentions += status != "abstain-degraded"
            else:
                wrong_abstentions += (status == "abstain-degraded" or
                                      (not is_positive and status != question["expected"]))
        else:
            invalid += 1
        if is_positive:
            positives.append(correct)
        else:
            controls.append(status == "answer" or answer.get("answer") not in (None, "")
                            or (status == "invalid-draft" and answer.get("claimed") is True))

    checks = {
        "answers_correct_supported": bool(positives) and sum(positives) / len(positives) >= thresholds["answers_correct_supported"],
        "unsupported_confident_on_controls": bool(controls) and sum(controls) / len(controls) <= thresholds["unsupported_confident_on_controls_max"],
        "citation_resolution": bool(citations) and sum(citations) / len(citations) == thresholds["citation_resolution"],
        "valid_responses": invalid == 0,
        "abstention_reasons": wrong_abstentions == 0,
        "semantic_review_complete": pending == 0,
    }
    return {
        "subset": subset, "questions": len(chosen),
        "answers_correct_supported": rate(positives),
        "unsupported_confident_on_controls": rate(controls),
        "citation_resolution": rate(citations),
        "invalid_responses": invalid, "wrong_abstentions": wrong_abstentions,
        "pending_semantic_reviews": pending, "checks": checks, "pass": all(checks.values()),
    }


def score_performance(rows: list[dict], publications: list[dict], peak_rss: int, thresholds: dict) -> dict:
    def p95(samples: list[dict]) -> float | None:
        values = sorted(sample["seconds"] for sample in samples)
        if not values or any(not math.isfinite(value) or value < 0 for value in values):
            return None
        return values[math.ceil(len(values) * .95) - 1]

    lanes = Counter(row["reader"] for row in rows)
    positions = {(row["reader"], row["step"]) for row in rows}
    overlap = {row["reader"] for row in rows if any(
        row["start"] <= event["commit_at"] <= row["end"] for event in publications
    )}
    recall, visible = p95(rows), p95(publications)
    checks = {
        "workload": len(lanes) == 10 and len(rows) >= 100 and len(positions) == len(rows) and min(lanes.values()) >= 10,
        "context": bool(rows) and all(row["result"] == "context" and row["coverage"] in
                                      {"hybrid-current", "hybrid-stale"} for row in rows),
        "overlap": len(overlap) == 10,
        "warm_recall_p95": recall is not None and recall <= thresholds["warm_recall_p95_seconds"],
        "visibility_p95": visible is not None and visible <= thresholds["visibility_p95_seconds"],
        "exact_visibility": bool(publications) and all(event["exact"] is True for event in publications),
        "service_rss": 0 < peak_rss <= thresholds["rss_max_bytes"],
    }
    return {"warm_samples": len(rows), "readers": len(lanes), "readers_overlapping_publication": len(overlap),
            "coverage": dict(Counter(row["coverage"] or "no-context" for row in rows)),
            "publications": len(publications), "warm_recall_p95_seconds": recall,
            "committed_to_observed_hybrid_p95_seconds": visible, "service_peak_rss_bytes": peak_rss,
            "checks": checks, "pass": all(checks.values())}
