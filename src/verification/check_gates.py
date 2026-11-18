#!/usr/bin/env python3
"""Report G0-G8 check status from receipts. Never runs tests, models or hosts.

    python3 src/verification/check_gates.py [--json]

PASS         a clean-commit receipt for the current identity has every selected test passing
FAIL         such a receipt has a failing test, or its repeats disagreed
MISSING      no automated check exists yet, or no receipt/test covers it
STALE        receipts exist, but for different code, locks, corpus or runtime
EXPLORATORY  only dirty-tree receipts exist for the current identity

Exit 0 only if every check is PASS; 1 if anything FAILs or a receipt is
malformed; 2 otherwise (incomplete).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import receipts as R  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--receipts", type=Path, default=R.RECEIPT_DIR)
    args = parser.parse_args()

    gates = R.load_gates()
    receipts, problems = R.load_receipts(args.receipts)
    current = R.current_identity(model={"sha256": R.approved_model_sha256()})
    rows = R.evaluate(gates, receipts, current)
    code = R.exit_code(rows, problems)

    if args.json:
        print(json.dumps({"commit": current["commit"], "dirty": current["dirty"],
                          "rows": rows, "problems": problems, "exit": code}, indent=1))
        return code
    print(f"commit {current['commit'][:12]}{' (dirty)' if current['dirty'] else ''}")
    width = max(len(r["check"]) for r in rows)
    for r in rows:
        print(f"  {r['gate']:<3} {r['check']:<{width}}  {r['tier']}  {r['status']:<11} {r['detail']}")
    for p in problems:
        print(f"  MALFORMED RECEIPT {p}")
    counts = {s: sum(r["status"] == s for r in rows) for s in R.STATUSES}
    print(" ".join(f"{s}={n}" for s, n in counts.items() if n))
    print({0: "ALL CHECKS PASS", 1: "FAILED", 2: "INCOMPLETE"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main())
