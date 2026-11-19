"""Run and score the bounded ten-reader v2 performance workload."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from g2_reranker_profile import approved_settings, valid_settings
from measure_v2 import ROOT, build_v2, publish_holdout, receipts, resolve, verified_frozen
from retrieval_run import read_retrieval_run
from score_v2 import score_performance, score_retrieval


def quality_under_load(rows: list[dict], questions: list[dict], rankings: dict, thresholds: dict) -> dict:
    by_id = {q["id"]: q for q in questions}
    ordered = [row["id"] for row in rows]
    if len(set(ordered)) != len(ordered) or not set(ordered) <= by_id.keys():
        raise ValueError("performance question IDs must be unique and frozen")
    groups = defaultdict(list)
    for row in rows:
        category = row["coverage"] or row["result"]
        if row["degradation"]:
            category += ":" + row["degradation"]
        groups[category].append(row["id"])

    def metrics(ids):
        # A performance sample is smaller than the complete held-out split.
        report = score_retrieval([by_id[qid] for qid in ids], dict.fromkeys(ids, "development"),
                                 rankings, thresholds, subset="development")
        return {k: v for k, v in report.items() if k not in {"subset", "checks", "pass"}}

    return {"all": metrics(ordered), "groups": {key: metrics(ids) for key, ids in sorted(groups.items())}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="a completed v2 retrieval run")
    parser.add_argument("--development", action="store_true", help="measure the development partition without publishing")
    args = parser.parse_args()
    subset = "development" if args.development else "holdout"
    runs = (build_v2.WORK / "runs").resolve()
    run = (runs / args.run_id).resolve()
    if run.parent != runs or run.name != args.run_id:
        parser.error("run_id must name a directory under .cache/eval/v2/runs")
    try:
        model = Path(os.environ["WIKI_TEST_CACHED_MODEL"]).resolve(strict=True)
        reranker = Path(os.environ["WIKI_EVAL_RERANKER"]).resolve(strict=True)
    except (KeyError, OSError):
        parser.error("set WIKI_TEST_CACHED_MODEL and WIKI_EVAL_RERANKER to the pinned model files")
    if receipts.sha256_file(model) != receipts.approved_model_sha256() or \
            receipts.sha256_file(reranker) != receipts.approved_reranker_sha256():
        raise SystemExit("performance measurement requires the approved model hashes")
    approved = approved_settings()
    identity = receipts.current_identity(model={"sha256": receipts.approved_model_sha256()})
    artifacts = read_retrieval_run(run)
    retrieval = artifacts.report
    if ((identity["dirty"] and not args.development)
            or identity != artifacts.provenance.get("identity")
            or retrieval.get("subset") != subset
            or retrieval.get("manifest_sha256") != receipts.sha256_file(build_v2.MANIFEST)
            or retrieval.get("reranker_sha256") != receipts.approved_reranker_sha256()
            or not valid_settings(retrieval.get("reranker_config"))
            or (not args.development and retrieval["reranker_config"] != approved)):
        raise SystemExit(f"performance measurement requires a current v2 {subset} run with the approved profile")
    manifest, questions, split, _, _ = verified_frozen()
    expected = [{k: q[k] for k in ("id", "query", "project")} for q in questions if split[q["id"]] == subset]
    if json.loads((run / "questions.json").read_text()) != expected:
        raise SystemExit(f"performance questions do not match the frozen {subset} partition")
    output = run / "performance"
    if output.exists():
        raise SystemExit("performance output already exists for this run")
    command = ["node", "node_modules/tsx/dist/cli.mjs", "src/eval/perf_v2.ts",
               str(run), str(output), str(model), str(reranker)]
    if args.development:
        command.append("--development")
    try:
        subprocess.run(command, cwd=ROOT, timeout=1080, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        raise SystemExit("performance workload did not finish; partial run data retained") from None
    if identity != receipts.current_identity(model=identity["model"]):
        raise SystemExit("checkout identity changed during performance measurement")
    raw = output / "performance.json"
    data = json.loads(raw.read_text())
    if (data["commit"] != identity["commit"] or data["manifest_sha256"] != retrieval["manifest_sha256"]
            or data["script_sha256"] != receipts.sha256_file(ROOT / "src/eval/perf_v2.ts")):
        raise SystemExit("performance observations do not match the run provenance")
    observed = data.get("reranker")
    if (not valid_settings(observed) or data.get("reranker_sha256") != receipts.approved_reranker_sha256()
            or (not args.development and observed != approved)):
        raise SystemExit("performance observations differ from the required reranker profile")
    if args.development and observed != retrieval["reranker_config"]:
        raise SystemExit("performance reranker settings differ from the retrieval run")
    report = score_performance(data["rows"], data["visibility"], data["service_peak_rss_bytes"], manifest["thresholds"])
    rankings = resolve(output / "authority.db", {"rankings": {
        row["id"]: {"status": row["result"], "coverage": row["coverage"], "bytes": row["bytes"],
                    "seconds": row["seconds"], "passages": row["passages"]} for row in data["rows"]
    }})
    report["under_load_quality"] = quality_under_load(data["rows"], questions, rankings, manifest["thresholds"])
    report.update({"commit": identity["commit"], "manifest_sha256": data["manifest_sha256"],
                   "reranker_config": observed, "reranker_sha256": data["reranker_sha256"],
                   "observations_sha256": receipts.sha256_file(raw), "scope": data["scope"],
                   "subset": subset, "sampled_process_tree_peak_rss_bytes": data["sampled_process_tree_peak_rss_bytes"]})
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not args.development:
        publish_holdout("g2.performance", run, report_path, report["pass"])
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
