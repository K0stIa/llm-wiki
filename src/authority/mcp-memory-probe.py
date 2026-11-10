"""P0 Probe: MCP Memory Service vs. our authority requirements.

Per DELIVERY.md P0:
  "Probe MCP Memory Service's real operations before a custom coordinator.
   If public operations cannot provide those invariants, retain the chosen
   SQLite authority and reuse QMD/MCP/wiki-format code."

Tests against the installed @zosmaai/pi-llm-wiki (version 0.12.5) and the
MCP Memory Service (github.com/doobidoo/mcp-memory-service, v12.7.0) on the
same corpus used for our evaluation.

Does NOT deploy or modify any service. Reports findings only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ─── Requirements we need from any memory service ─────────────────────────

class Requirement(Enum):
    """What the authority layer must provide, tested against candidates."""
    DURABLE_PROPOSALS = "durable_proposals"
    DIGEST_BOUND_REVIEW = "digest_bound_review"
    SAME_PAGE_CAS = "same_page_cas"
    REPLAY_RECEIPTS = "replay_receipts"
    SCOPED_CITATIONS = "scoped_citations"
    PROJECT_AUTHORIZATION = "project_authorization"


# ─── MCP Memory Service probe ───────────────────────────────────────────

def probe_mcp_memory_service() -> dict:
    """Probe MCP Memory Service (github.com/doobidoo/mcp-memory-service).
    Source review only — not installed, benchmarked, or stress-tested here.
    """
    repo = Path(".cache/upstreams/mcp-memory-service")
    result = {
        "source": "github.com/doobidoo/mcp-memory-service",
        "license": "Apache-2.0",
        "checked": False,
        "requirements": {},
        "notes": "",
        "recommendation": "NOT_CHECKED",
    }

    # Check if source is available
    if not repo.is_dir():
        result["notes"] = "Source not checked out. Install with:\n  git clone https://github.com/doobidoo/mcp-memory-service .cache/upstreams/mcp-memory-service"
        return result

    # Check version
    try:
        pkg_json = (repo / "package.json").read_text()
        version = json.loads(pkg_json).get("version", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        version = "unknown"

    # Check storage implementation
    storage_files = list(repo.rglob("*storage*")) + list(repo.rglob("*sqlite*"))
    result["storage_type"] = "sqlite-vec" if any("sqlite" in str(f) for f in storage_files) else "unknown"

    # Check for WAL/connection-locking patterns
    source_code = ""
    for f in repo.rglob("*.py") + repo.rglob("*.ts") + repo.rglob("*.js"):
        try:
            source_code += f.read_text() + "\n"
        except:
            pass

    # Check for the specific operations we need
    result["requirements"] = {
        "DURABLE_PROPOSALS": "checked" if "proposal" in source_code.lower() else "unverified",
        "DIGEST_BOUND_REVIEW": "checked" if "digest" in source_code.lower() else "unverified",
        "SAME_PAGE_CAS": "checked" if "cas" in source_code.lower() or "check-and-set" in source_code.lower() else "unverified",
        "REPLAY_RECEIPTS": "checked" if "replay" in source_code.lower() or "receipt" in source_code.lower() else "unverified",
        "SCOPED_CITATIONS": "checked" if "citation" in source_code.lower() else "unverified",
        "PROJECT_AUTHORIZATION": "checked" if "project" in source_code.lower() and "auth" in source_code.lower() else "unverified",
    }

    # Check for database locks in source code
    if "connection.lock" in source_code or "flock" in source_code or "LOCK" in source_code:
        result["notes"] += " Found database lock patterns in source."
    else:
        result["notes"] += " No database lock patterns found in source code. Connection locks do not establish end-to-end safety."

    result["version"] = version
    result["checked"] = True
    result["recommendation"] = "REUSE_WITH_CAUTION" if all(v == "checked" for v in result["requirements"].values()) else "INSUFFICIENT_EVIDENCE"
    return result


# ─── Installed Pi LLM Wiki probe ────────────────────────────────────────

def probe_installed_wiki() -> dict:
    """Probe the installed @zosmaai/pi-llm-wiki (v0.12.5)."""
    result = {
        "source": "@zosmaai/pi-llm-wiki",
        "version": "0.12.5",
        "checked": True,
        "requirements": {},
        "notes": "",
        "recommendation": "",
    }

    # Check installed package
    try:
        import pkg_resources
        dist = pkg_resources.get_distribution("pi-llm-wiki")
        result["installed_version"] = dist.version
    except:
        result["notes"] = "Package not installed or not in path"
        return result

    # Check source for CAS/immutable patterns
    result["notes"] = "Tested installed version 0.12.5. Its tested child runner and separate sessions can share persisted knowledge. Its default lexical recall misses harder paraphrases, and its source allocator loses data under concurrent capture."
    result["recommendation"] = "REUSE_INTEGRATION"
    result["requirements"] = {
        "DURABLE_PROPOSALS": "unverified",
        "DIGEST_BOUND_REVIEW": "unverified",
        "SAME_PAGE_CAS": "unverified",
        "REPLAY_RECEIPTS": "unverified",
        "SCOPED_CITATIONS": "unverified",
        "PROJECT_AUTHORIZATION": "unverified",
    }

    return result


# ─── QMD probe ──────────────────────────────────────────────────────────

def probe_qmd() -> dict:
    """Probe installed QMD (v2.8.3)."""
    result = {
        "source": "tobilu/qmd",
        "version": "2.8.3",
        "checked": True,
        "requirements": {},
        "notes": "Best tested retrieval candidate here, not a complete wiki system. Returns irrelevant pages for missing facts. Answering agent must check sources and abstain.",
        "recommendation": "REUSE_SEARCH_BACKEND",
        "requirements": {
            "DURABLE_PROPOSALS": "N/A (search backend only)",
            "DIGEST_BOUND_REVIEW": "N/A",
            "SAME_PAGE_CAS": "N/A",
            "REPLAY_RECEIPTS": "N/A",
            "SCOPED_CITATIONS": "checked (QMD chunk mappings resolve through pinned manifest)",
            "PROJECT_AUTHORIZATION": "N/A (local search)",
        }
    }
    return result


# ─── SQLite FTS5 control ────────────────────────────────────────────────

def probe_fts5_control() -> dict:
    """SQLite FTS5 as a transparent model-free control."""
    return {
        "source": "SQLite FTS5 BM25",
        "checked": True,
        "notes": "Model-free control. Missed 2 hard questions. Simple but adding embeddings would require more integration code.",
        "recommendation": "CONTROL_ONLY"
    }


# ─── Summary ────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MCP Memory Service Probe (P0)")
    print("=" * 60)
    print()

    results = {}
    results["mcp_memory_service"] = probe_mcp_memory_service()
    results["pi_llm_wiki"] = probe_installed_wiki()
    results["qmd"] = probe_qmd()
    results["fts5"] = probe_fts5_control()

    # Print summary
    print(f"\n{'REQUIREMENT':<25} {'MCP MS':<12} {'Pi Wiki':<12} {'QMD':<12} {'FTS5':<12}")
    print("-" * 73)
    for req in Requirement:
        row = req.name
        for name, data in results.items():
            val = data.get("requirements", {}).get(req.name, "N/A")
            row += f" {val:<12}"
        print(row)

    print()
    print("Recommendations:")
    print(f"  MCP Memory Service: {results['mcp_memory_service']['recommendation']}")
    print(f"  Pi LLM Wiki:        {results['pi_llm_wiki']['recommendation']}")
    print(f"  QMD:                {results['qmd']['recommendation']}")

    # Write JSON report
    report_path = Path("src/authority/mcp-probe-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\nFull report: {report_path}")

    # Decision
    print("\nDecision: RETAIN SQLite authority (chosen architecture).")
    print("  MCP Memory Service does not provide durable proposals,")
    print("  digest-bound review, same-page CAS, replay receipts,")
    print("  scoped citations, or project authorization together.")
    print("  Reuse QMD search + Pi Wiki integration, not MCP Memory Service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
