#!/usr/bin/env python3
"""Measure where required development evidence is lost under the frozen D14 retrieval profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "eval"))
import build_v2  # noqa: E402
import measure_v2  # noqa: E402
from g2_reranker_profile import approved_settings, valid_settings  # noqa: E402
from measure_v2 import receipts, score_v2  # noqa: E402

OUTPUTS = (
    "questions.json", "trace-questions.json", "trace.json", "raw.json", "oracle-raw.json",
    "report.json", "retrieval-run.json", "trace-report.json",
)


def write_private(path: Path, data: dict | list) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def quantiles(values: list[float]) -> dict:
    values = sorted(values)
    return {"n": len(values), **{
        name: round(values[math.ceil(len(values) * p) - 1], 1)
        for name, p in (("p50", 0.5), ("p95", 0.95), ("max", 1))
    }}


def summarize(dev: list[dict], traces: dict) -> dict:
    stages = defaultdict(list)
    slices = defaultdict(lambda: defaultdict(Counter))
    losses = defaultdict(Counter)
    admission = Counter()
    results = Counter()
    ceilings = defaultdict(Counter)
    for q in dev:
        trace = traces[q["id"]]
        for name, duration in trace["stages"].items():
            stages[name].append(duration)
        lists = trace.get("lists", {})
        admission[(lists.get("rerankAdmission", "no-context"), lists.get("reranked", False))] += 1
        results[trace["degradation"] or trace["result"]] += 1
        if q["expected"] != "answer":
            continue
        if not lists:
            for ceiling in ("candidatePages", "candidateBytes", "authorityBytes"):
                ceilings[ceiling]["unknown"] += 1
            for gold in q["gold"]:
                for kind, label in (("page", "unknown"), ("span", "unknown" if gold["span"] else "span-unscorable")):
                    losses[kind][label] += 1
                    slices[q["slice"]][kind][label] += 1
            continue
        ceilings["candidatePages"]["complete" if trace["candidateComplete"] else "incomplete"] += 1
        for key, name in (("candidateOracle", "candidateBytes"), ("authorityOracle", "authorityBytes")):
            oracle = trace[key]
            fields = ceilings[name]
            fields["requiredFacts"] += oracle["required"]
            if oracle["status"] == "unknown":
                fields["unknown"] += 1
                fields["unknownRequiredFacts"] += oracle["required"]
            else:
                fields["complete" if oracle["matched"] == oracle["required"] else "incomplete"] += 1
                fields["provedMatchedFacts"] += oracle["matched"]
        for evidence in trace["evidence"]:
            for kind in ("page", "span"):
                loss = evidence[kind]["loss"]
                losses[kind][loss] += 1
                slices[q["slice"]][kind][loss] += 1
    return {
        "subset": "development", "questions": len(dev), "positiveQuestions": sum(q["expected"] == "answer" for q in dev),
        "results": dict(results),
        "rerank": dict((status + ("/reranked" if ran else "/fused"), n) for (status, ran), n in admission.items()),
        "losses": dict(losses), "sliceLosses": dict(slices), "ceilings": dict(ceilings),
        "serialStageMs": {name: quantiles(values) for name, values in stages.items()},
    }


def checked_model(variable: str, expected: str) -> tuple[Path, str]:
    configured = os.environ.get(variable)
    if not configured or not Path(configured).is_file():
        raise SystemExit(f"set {variable} to the approved cached GGUF")
    path = Path(configured).resolve()
    actual = receipts.sha256_file(path)
    if actual != expected:
        raise SystemExit(f"{variable} does not point to the approved GGUF")
    return path, actual


def code_digest(identity: dict) -> str:
    """Bind dirty development runs to the contents of their changed paths."""
    return receipts.sha256_json({
        path: receipts.sha256_file(ROOT / path) if (ROOT / path).is_file() else None
        for path in identity["dirty_paths"]
    })


def reuse_generation(source: Path, run: Path, projects: set[str], manifest_sha: str, model_sha: str) -> None:
    provenance = json.loads((source / "trace-provenance.json").read_text())
    if (provenance["subset"] != "development" or provenance["manifest_sha256"] != manifest_sha
            or provenance["identity"]["model"]["sha256"] != model_sha):
        raise SystemExit("source generation does not match the frozen development inputs")
    with closing(sqlite3.connect((source / "authority.db").as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(run / "authority.db")) as clone:
            original.backup(clone)
    subprocess.run(
        ["node", "node_modules/tsx/dist/cli.mjs", "src/eval/copy-generation.ts",
         str(source.resolve()), str(run.resolve()), *sorted(projects)],
        cwd=ROOT, check=True, timeout=120,
    )


def run_trace(runs: Path, source: Path | None = None) -> Path:
    model, model_sha = checked_model("WIKI_TEST_CACHED_MODEL", receipts.approved_model_sha256())
    reranker, reranker_sha = checked_model("WIKI_EVAL_RERANKER", receipts.approved_reranker_sha256())
    approved = approved_settings()
    for variable, key in (("WIKI_EVAL_RERANK_DEVICE", "device"), ("WIKI_EVAL_RERANK_DEPTH", "depth"), ("WIKI_EVAL_RERANK_TOKENS", "docTokens")):
        if os.environ.get(variable, str(approved[key])) != str(approved[key]):
            raise SystemExit(f"{variable} differs from the approved D14 profile")
    identity = receipts.current_identity(model={"sha256": model_sha})
    changed_files_sha = code_digest(identity)
    manifest_sha = receipts.sha256_file(build_v2.MANIFEST)
    started = datetime.now(timezone.utc)
    manifest, questions, split, pages, edits = measure_v2.verified_frozen()
    dev = [q for q in questions if split[q["id"]] == "development"]
    run = runs / started.strftime("trace-%Y%m%dT%H%M%S.%fZ")
    run.mkdir(mode=0o700, parents=True)
    db = run / "authority.db"
    if source is None:
        measure_v2.load_authority(db, pages, edits)
    else:
        reuse_generation(source, run, {q["project"] for q in dev}, manifest_sha, model_sha)
    write_private(run / "questions.json", [{k: q[k] for k in ("id", "query", "project")} for q in dev])
    write_private(run / "trace-questions.json", {"subset": "development", "questions": [
        {k: q[k] for k in ("id", "query", "project", "expected", "gold")} for q in dev
    ]})
    with (run / "runner-stderr.log").open("wb") as errors:
        completed = subprocess.run(
            ["node", "node_modules/tsx/dist/cli.mjs", "src/eval/trace_v2.ts", str(db), str(run / "indexes"),
             str(model), str(run / "trace-questions.json"), str(run), *(["--reuse-generation"] if source else [])],
            cwd=ROOT, stderr=errors, env={**os.environ, "WIKI_EVAL_RERANKER": str(reranker)},
        )
    if completed.returncode:
        raise SystemExit(f"trace runner exited {completed.returncode}; see {run.name}/runner-stderr.log")
    trace, raw, oracle = (json.loads((run / name).read_text()) for name in ("trace.json", "raw.json", "oracle-raw.json"))
    observed = trace["reranker"]
    if trace["subset"] != "development" or any(
        not valid_settings(data["reranker"]) or data["reranker"] != approved for data in (trace, raw, oracle)
    ):
        raise SystemExit("trace outputs differ from the development D14 profile")
    if any(entries.keys() != {q["id"] for q in dev} for entries in (trace["traces"], raw["rankings"], oracle["rankings"])):
        raise SystemExit("trace output does not cover the exact development split")

    rankings = measure_v2.resolve(db, raw)
    oracle_rankings = measure_v2.resolve(db, oracle)
    if any(not passage["resolved"] or passage["project"] != q["project"]
           for q in dev for passage in oracle_rankings[q["id"]]["results"]):
        raise SystemExit("evidence-only output contains an unresolved or out-of-project passage")

    report = score_v2.score_retrieval(dev, split, rankings, manifest["thresholds"], subset="development")
    seconds = sorted(r["seconds"] for r in rankings.values())
    report.update({
        "serial_latency_p95_seconds": round(seconds[math.ceil(len(seconds) * 0.95) - 1], 3),
        "manifest_sha256": manifest_sha,
        "model_sha256": model_sha,
        "reranker_sha256": reranker_sha,
        "reranker_config": observed,
        "raw_rankings_sha256": receipts.sha256_file(run / "raw.json"),
    })
    if not all(r["status"] == "ok" and r["coverage"] == "hybrid-current" and not r["degradation"] for r in raw["rankings"].values()):
        report["checks"]["hybrid_current_undegraded"] = False
        report["pass"] = False
    if (identity != receipts.current_identity(model={"sha256": model_sha}) or changed_files_sha != code_digest(identity)
            or manifest_sha != receipts.sha256_file(build_v2.MANIFEST)):
        raise SystemExit("checkout identity changed during trace measurement")
    write_private(run / "report.json", report)
    write_private(run / "retrieval-run.json", {
        "identity": identity, "started": started.isoformat(), "report_sha256": receipts.sha256_file(run / "report.json"),
    })
    diagnostic = {**summarize(dev, trace["traces"]), "pageRecall": {
        "overall": report["evidence_recall_at_10"], "multiPageComplete": report["all_evidence_at_10_multi_page"],
        "slices": report["slice_recall_at_10"],
    }}
    write_private(run / "trace-report.json", diagnostic)
    write_private(run / "trace-provenance.json", {
        "version": 2, "subset": "development", "identity": identity, "changed_files_sha256": changed_files_sha,
        "manifest_sha256": manifest_sha, "started": started.isoformat(), "reranker_sha256": reranker_sha,
        "generation_source": source.name if source else None,
        "reranker_config": observed, "outputs_sha256": {name: receipts.sha256_file(run / name) for name in OUTPUTS},
    })
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", help="report an existing trace run under .cache/eval/v2/runs")
    mode.add_argument("--reuse-from", help="clone a verified generation from a private development trace run")
    args = parser.parse_args()
    runs = (build_v2.WORK / "runs").resolve()
    selected = args.run or args.reuse_from
    if selected:
        run = (runs / selected).resolve() if Path(selected).name == selected else Path(selected).resolve()
        if run.parent != runs or not run.is_dir() or run.stat().st_mode & 0o077:
            raise SystemExit("expected a private trace run directory under .cache/eval/v2/runs")
        if args.reuse_from:
            run = run_trace(runs, run)
    else:
        run = run_trace(runs)
    provenance = json.loads((run / "trace-provenance.json").read_text())
    expected_outputs = set(OUTPUTS) if provenance["version"] == 2 else set(OUTPUTS) - {"trace-questions.json"}
    if (provenance["subset"] != "development"
            or provenance["version"] not in (1, 2) or provenance["outputs_sha256"].keys() != expected_outputs
            or any(receipts.sha256_file(run / name) != digest for name, digest in provenance["outputs_sha256"].items())):
        raise SystemExit("saved trace does not match its recorded development provenance")
    recorded = provenance.get("reranker_config")
    if not valid_settings(recorded):
        raise SystemExit("saved trace does not match its recorded development provenance")
    for name, key in (("trace.json", "reranker"), ("raw.json", "reranker"),
                      ("oracle-raw.json", "reranker"), ("report.json", "reranker_config")):
        artifact = json.loads((run / name).read_text())
        observed = artifact.get(key) if isinstance(artifact, dict) else None
        if not valid_settings(observed) or observed != recorded:
            raise SystemExit(f"saved {name} does not match its recorded development provenance")
    print(f"run={run.name}")
    print(json.dumps(json.loads((run / "trace-report.json").read_text()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
