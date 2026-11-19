"""Read and verify the artifacts consumed from a saved v2 retrieval run."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetrievalRun:
    provenance: dict
    provenance_sha256: str
    report: dict


def _read_object(data: bytes) -> dict:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def read_retrieval_run(run: Path) -> RetrievalRun:
    """Verify each consumed artifact against the digest of the bytes being parsed."""
    try:
        provenance_bytes = (run / "retrieval-run.json").read_bytes()
        provenance = _read_object(provenance_bytes)
        report_bytes = (run / "report.json").read_bytes()
        if provenance["report_sha256"] != hashlib.sha256(report_bytes).hexdigest():
            raise SystemExit("retrieval report does not match the recorded run")
        report = _read_object(report_bytes)
        return RetrievalRun(provenance, hashlib.sha256(provenance_bytes).hexdigest(), report)
    except (OSError, ValueError, KeyError):
        raise SystemExit("could not validate retrieval artifacts") from None


def read_raw_rankings(run: Path, report: dict) -> dict:
    """Read raw rankings attested by an already verified retrieval report."""
    try:
        raw_bytes = (run / "raw.json").read_bytes()
        if report["raw_rankings_sha256"] != hashlib.sha256(raw_bytes).hexdigest():
            raise SystemExit("raw rankings do not match the recorded retrieval run")
        return _read_object(raw_bytes)
    except (OSError, ValueError, KeyError):
        raise SystemExit("could not validate retrieval artifacts") from None
