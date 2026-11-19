#!/usr/bin/env python3
"""Measure eval v2 retrieval: load authority, rank with real hybrid recall, resolve, score.

    WIKI_TEST_CACHED_MODEL=... python3 src/eval/measure_v2.py [--subset holdout|development]

CONFIDENTIAL: the run directory (.cache/eval/v2/runs/<id>/) holds the database,
indexes and raw rankings. stdout and report.json hold numbers and hashes only.
Refuses to run unless the frozen data matches the committed manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "authority"))
sys.path.insert(0, str(ROOT / "src" / "eval"))
sys.path.insert(0, str(ROOT / "src" / "verification"))
from authority import ChangeKind, DecisionKind, connect_knowledge  # noqa: E402
import build_v2  # noqa: E402
from g2_reranker_profile import approved_settings, valid_settings  # noqa: E402
import receipts  # noqa: E402
from retrieval_run import read_retrieval_run  # noqa: E402
import score_v2  # noqa: E402

FROZEN = build_v2.WORK / "frozen"


def verified_frozen() -> tuple[dict, list, dict, list, list]:
    manifest = json.loads(build_v2.MANIFEST.read_text())
    for name, digest in manifest["files_sha256"].items():
        if hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"frozen file {name} does not match the committed manifest")
    load = lambda n: json.loads((FROZEN / n).read_text())  # noqa: E731
    return manifest, load("questions.json"), load("split.json"), load("pages.json"), load("edits.json")


def load_authority(db: Path, pages: list, edits: list) -> None:
    """Real pages by owner; synthetic edits through the normal paths."""
    main = connect_knowledge(str(db), "main")
    for p in pages:
        main.create_page("main", p["id"], p["title"], p["body"], "owner")
    titles = {p["id"]: p["title"] for p in pages}
    lookalike = None
    for e in sorted(edits, key=lambda e: (e["kind"], e["page"])):
        if e["kind"] == "supersede":
            head = main.page("main", e["page"])
            receipt = main.propose("main", e["page"], head.revision, ChangeKind.REPLACE, titles[e["page"]], e["body"], "worker", [])
            if not receipt or main.decide("main", receipt.key, DecisionKind.PUBLISH).kind != "committed":
                raise SystemExit("supersede edit failed to publish")
        elif e["kind"] == "child":
            main.create_page("main", e["page"], e["title"], e["body"], "child")
        elif e["kind"] == "conflict":
            main.create_page("main", e["page"], e["title"], e["body"], "owner")
        elif e["kind"] == "lookalike":
            lookalike = lookalike or connect_knowledge(str(db), "lookalike")
            lookalike.create_page("lookalike", e["page"], titles[e["page"]], e["body"], "owner")
        else:
            raise SystemExit("unknown edit kind")


def resolve(db: Path, raw: dict) -> dict:
    """Attach project + exact-resolution flag to every passage, from the database itself."""
    rankings = {}
    with sqlite3.connect(db) as c:
        for qid, r in raw["rankings"].items():
            results = []
            for p in r["passages"]:
                page = p.get("page") or p.get("source")
                if "page" in p:
                    row = c.execute("SELECT project,body FROM page_revisions WHERE revision=? AND page=?",
                                    (p["revision"], p["page"])).fetchone()
                else:
                    row = c.execute("SELECT project,text FROM evidence_revisions WHERE revision=?", (p["revision"],)).fetchone()
                lines = row[1].split("\n") if row else []
                resolved = (bool(row) and 1 <= p["start"] <= p["end"] <= len(lines)
                            and "h:" + hashlib.sha256(row[1].encode()).hexdigest() == p["hash"]
                            and "\n".join(lines[p["start"] - 1:p["end"]]) == p["text"])
                results.append({"project": row[0] if row else None, "page": page, "revision": p["revision"],
                                "hash": p["hash"], "start": p["start"], "end": p["end"],
                                "resolved": resolved, "text": p["text"]})
            rankings[qid] = {"results": results, "coverage": r.get("coverage", r["status"]), "bytes": r["bytes"],
                             "seconds": r["seconds"]}
    return rankings


def publish_holdout(check: str, run: Path, report: Path, passed: bool) -> None:
    artifacts = read_retrieval_run(run)
    provenance, settings = artifacts.provenance, artifacts.report
    if settings.get("subset") != "holdout":
        return
    approved = approved_settings()
    model_sha = receipts.approved_reranker_sha256()
    reports = [settings]
    report_sha256 = provenance["report_sha256"] if report == run / "report.json" else None
    if check == "g2.performance":
        performance_bytes = report.read_bytes()
        reports.append(json.loads(performance_bytes))
        report_sha256 = hashlib.sha256(performance_bytes).hexdigest()
    for measured in reports:
        if (not isinstance(measured, dict) or measured.get("subset") != "holdout"
                or not valid_settings(measured.get("reranker_config")) or measured["reranker_config"] != approved
                or measured.get("reranker_sha256") != model_sha):
            print("Measurement receipt withheld because the run differs from the approved D14 profile.")
            return
    path = receipts.write_measurement(check, provenance["identity"], provenance["started"], report,
                                      passed, [Path(sys.executable).name, *sys.argv],
                                      report_sha256=report_sha256)
    print(f"Measurement receipt: {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", choices=["development", "holdout"], default="development")
    parser.add_argument("--answers", action="store_true", help="also collect answers from the approved local model")
    args = parser.parse_args()
    model = os.environ.get("WIKI_TEST_CACHED_MODEL")
    if not model or not Path(model).is_file():
        raise SystemExit("set WIKI_TEST_CACHED_MODEL to the approved cached GGUF")
    with open(model, "rb") as f:
        model_sha = hashlib.file_digest(f, "sha256").hexdigest()
    if model_sha != receipts.approved_model_sha256():
        raise SystemExit("model is not the approved embedding model")
    identity = receipts.current_identity(model={"sha256": model_sha})
    started = datetime.now(timezone.utc).isoformat()
    manifest, questions, split, pages, edits = verified_frozen()
    chosen = [q for q in questions if split[q["id"]] == args.subset]
    run = build_v2.WORK / "runs" / time.strftime("%Y%m%dT%H%M%S")
    run.mkdir(mode=0o700, parents=True)
    db = run / "authority.db"
    load_authority(db, pages, edits)
    (run / "questions.json").write_text(json.dumps([{k: q[k] for k in ("id", "query", "project")} for q in chosen], ensure_ascii=False))
    subprocess.run(["node", "node_modules/tsx/dist/cli.mjs", "src/eval/rank_v2.ts", str(db), str(run / "indexes"), model,
                    str(run / "questions.json"), str(run / "raw.json")], cwd=ROOT, check=True)
    raw = json.loads((run / "raw.json").read_text())
    rankings = resolve(db, raw)
    report = score_v2.score_retrieval(questions, split, rankings, manifest["thresholds"], subset=args.subset)
    seconds = sorted(r["seconds"] for r in rankings.values())
    report["serial_latency_p95_seconds"] = round(seconds[math.ceil(len(seconds) * 0.95) - 1], 3) if seconds else None
    report["manifest_sha256"] = hashlib.sha256(build_v2.MANIFEST.read_bytes()).hexdigest()
    report["model_sha256"] = model_sha
    report["raw_rankings_sha256"] = receipts.sha256_file(run / "raw.json")
    if os.environ.get("WIKI_EVAL_RERANKER"):
        with open(os.environ["WIKI_EVAL_RERANKER"], "rb") as f:
            report["reranker_sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
        report["reranker_config"] = raw.get("reranker")
    if not all(r["coverage"] == "hybrid-current" for r in rankings.values()):
        report["checks"]["hybrid_current"] = False
        report["pass"] = False
    if identity != receipts.current_identity(model={"sha256": model_sha}):
        raise SystemExit("checkout identity changed during retrieval measurement")
    report_path = run / "report.json"
    report_path.write_text(json.dumps(report, indent=1))
    (run / "retrieval-run.json").write_text(json.dumps({
        "identity": identity, "started": started, "report_sha256": receipts.sha256_file(report_path),
    }, indent=2) + "\n")
    printable = {k: v for k, v in report.items() if k != "checks"}
    print(json.dumps(printable, indent=1))
    print("checks:", json.dumps(report["checks"]))
    print("PASS" if report["pass"] else "FAIL", f"(report: {run.relative_to(ROOT)}/report.json)")
    publish_holdout("g2.recall-thresholds", run, report_path, report["pass"])
    if args.answers:
        import answer_v2

        answer_v2.collect(run, chosen, rankings, report, identity)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
