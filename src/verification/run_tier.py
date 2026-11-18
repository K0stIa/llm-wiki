#!/usr/bin/env python3
"""Run one verification tier and write a receipt.

    .venv/bin/python src/verification/run_tier.py --tier a [--repeat 2]
    WIKI_TEST_CACHED_MODEL=/path/model.gguf .venv/bin/python src/verification/run_tier.py --tier b

Tier a: deterministic core (no model, no network).
Tier b: pinned cached embedding model; fails, never skips, if it is absent or unapproved.
Tier c: installed agent-host configuration checks (live host scenarios are not here yet).

With --repeat N the tier runs N times; the receipt is deterministic only if
every run produced identical outcomes. Exit 0 only if all runs passed and
were identical. Run from a clean commit for the receipt to count as evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import receipts as R  # noqa: E402

PYTEST_MARKS = {"a": "not tier_b and not tier_c", "b": "tier_b", "c": "tier_c"}
# Node runtime tests are all tier a: none loads the embedding model.
NODE_TESTS = {"a": sorted(str(p.relative_to(R.ROOT)) for p in (R.ROOT / "tests" / "runtime").glob("*.test.mjs")),
              "b": [], "c": []}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def preflight(tier: str) -> dict | None:
    """Refuse to run against environments that do not match the locks."""
    for argv, what in ((["uv", "lock", "--check"], "uv.lock is out of date with pyproject.toml"),
                       (["uv", "sync", "--locked", "--check"], ".venv does not match uv.lock; run `uv sync --locked`"),
                       (["npm", "ls", "--all"], "node_modules does not match package-lock.json; run `npm ci`")):
        if subprocess.run(argv, cwd=R.ROOT, capture_output=True, timeout=120).returncode:
            raise SystemExit(f"preflight: {what}")
    if Path(sys.executable).resolve().parent != (R.ROOT / ".venv" / "bin").resolve():
        if Path(sys.prefix).resolve() != (R.ROOT / ".venv").resolve():
            raise SystemExit("preflight: run with the repository .venv interpreter")
    if tier != "b":
        return None
    path = os.environ.get("WIKI_TEST_CACHED_MODEL")
    if not path or not Path(path).is_file():
        raise SystemExit("tier b: set WIKI_TEST_CACHED_MODEL to the approved cached GGUF (downloads are forbidden)")
    digest = R.sha256_file(Path(path))
    if digest != R.approved_model_sha256():
        raise SystemExit(f"tier b: model {digest} is not the approved model")
    return {"sha256": digest, "bytes": Path(path).stat().st_size}


def run_pytest(tier: str, workdir: Path) -> tuple[dict, list[dict]]:
    out = workdir / "pytest-outcomes.json"
    argv = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-m", PYTEST_MARKS[tier]]
    env = {**os.environ, "WIKI_OUTCOMES_PATH": str(out), "HYPOTHESIS_PROFILE": "ci"}
    proc = subprocess.run(argv, cwd=R.ROOT, env=env, capture_output=True, text=True)
    (workdir / "pytest.log").write_text(proc.stdout + proc.stderr)
    outcomes = json.loads(out.read_text()) if out.is_file() else []
    # pytest exit 5 = nothing selected; anything nonzero otherwise is failure.
    return {"argv": argv[1:], "exit": proc.returncode, "log_tail": (proc.stdout + proc.stderr)[-2000:]}, outcomes


def run_node(test: str, workdir: Path) -> tuple[dict, list[dict]]:
    argv = ["node", "--import", "tsx", "--test", "--test-reporter=junit", test]
    proc = subprocess.run(argv, cwd=R.ROOT, capture_output=True, text=True)
    outcomes = []
    try:
        for case in ET.fromstring(proc.stdout).iter("testcase"):
            failed = case.find("failure") is not None or case.find("error") is not None
            skipped = case.find("skipped") is not None
            outcomes.append({"id": f"{test}::{case.get('name')}",
                             "outcome": "failed" if failed else "skipped" if skipped else "passed"})
    except ET.ParseError:
        pass
    if proc.returncode and not any(o["outcome"] == "failed" for o in outcomes):
        outcomes.append({"id": f"{test}::<file>", "outcome": "error"})
    return {"argv": argv, "exit": proc.returncode, "log_tail": proc.stderr[-2000:]}, outcomes


def run_typecheck() -> tuple[dict, list[dict]]:
    argv = ["node_modules/.bin/tsc", "-p", "tsconfig.json"]
    proc = subprocess.run(argv, cwd=R.ROOT, capture_output=True, text=True)
    outcome = "passed" if proc.returncode == 0 else "failed"
    return ({"argv": argv, "exit": proc.returncode, "log_tail": (proc.stdout + proc.stderr)[-2000:]},
            [{"id": "typecheck::tsconfig.json", "outcome": outcome}])


def run_once(tier: str, workdir: Path) -> tuple[list[dict], list[dict]]:
    commands, outcomes = [], []
    cmd, out = run_pytest(tier, workdir)
    commands.append(cmd)
    outcomes += out
    for test in NODE_TESTS[tier]:
        cmd, out = run_node(test, workdir)
        commands.append(cmd)
        outcomes += out
    if tier == "a":
        cmd, out = run_typecheck()
        commands.append(cmd)
        outcomes += out
    outcomes.sort(key=lambda o: o["id"])
    return commands, outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=R.TIERS, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=R.RECEIPT_DIR)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    model = preflight(args.tier)
    identity = R.current_identity(model=model)
    started = now()
    runs = []
    with tempfile.TemporaryDirectory(prefix="wiki-verify-") as tmp:
        for i in range(args.repeat):
            work = Path(tmp) / str(i)
            work.mkdir()
            runs.append(run_once(args.tier, work))
            print(f"run {i + 1}/{args.repeat}: {sum(o['outcome'] == 'passed' for o in runs[-1][1])} passed, "
                  f"{sum(o['outcome'] in ('failed', 'error') for o in runs[-1][1])} failed", file=sys.stderr)

    digests = [R.sha256_json(outcomes) for _, outcomes in runs]
    commands, outcomes = runs[-1]
    deterministic = len(set(digests)) == 1
    receipt = {
        "schema": R.RECEIPT_SCHEMA,
        "tier": args.tier,
        "run_id": str(uuid.uuid4()),
        "started": started,
        "finished": now(),
        "identity": identity,
        "commands": commands,
        "repeat": args.repeat,
        "run_outcome_digests": digests,
        "deterministic": deterministic,
        "outcomes": outcomes,
        "outcomes_sha256": R.sha256_json(outcomes),
    }
    R.validate_receipt(receipt)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{receipt['finished'].replace(':', '')}-tier-{args.tier}-{receipt['run_id'][:8]}.json"
    path.write_text(json.dumps(receipt, indent=1) + "\n")

    failed = [o["id"] for o in outcomes if o["outcome"] in ("failed", "error")]
    commands_failed = any(c["exit"] not in (0,) for run in runs for c in run[0])
    print(f"receipt: {path.relative_to(R.ROOT) if path.is_relative_to(R.ROOT) else path}")
    print(f"tier {args.tier}: {len(outcomes)} tests, {len(failed)} failing, "
          f"deterministic={deterministic}, dirty={identity['dirty']}")
    if identity["dirty"]:
        print("note: dirty tree -> receipt is EXPLORATORY and does not count as gate evidence")
    for test in failed[:20]:
        print(f"  FAIL {test}")
    return 0 if deterministic and not failed and not commands_failed else 1


if __name__ == "__main__":
    sys.exit(main())
