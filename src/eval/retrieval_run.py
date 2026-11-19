"""Read and verify the artifacts consumed from a saved v2 retrieval run."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetrievalRun:
    provenance: dict
    report: dict


class ReportDigestMismatch(ValueError):
    """The report bytes differ from the retrieval run attestation."""


def _read_object(data: bytes) -> dict:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def read_provenance(run: Path) -> tuple[dict, str]:
    data = (run / "retrieval-run.json").read_bytes()
    return _read_object(data), hashlib.sha256(data).hexdigest()


def read_verified_report(run: Path, provenance: dict) -> dict:
    """Verify and parse a single snapshot of the retrieval report."""
    data = (run / "report.json").read_bytes()
    report = _read_object(data)
    if provenance["report_sha256"] != hashlib.sha256(data).hexdigest():
        raise ReportDigestMismatch
    return report


def read_retrieval_run(run: Path) -> RetrievalRun:
    """Read provenance and report for callers that check their eligibility together."""
    try:
        provenance, _ = read_provenance(run)
        return RetrievalRun(provenance, read_verified_report(run, provenance))
    except ReportDigestMismatch:
        raise SystemExit("retrieval report does not match the recorded run") from None
    except (OSError, ValueError, KeyError):
        raise SystemExit("could not validate retrieval artifacts") from None


def read_raw_rankings(run: Path, report: dict) -> dict:
    """Read raw rankings attested by an already verified retrieval report."""
    data = (run / "raw.json").read_bytes()
    if report["raw_rankings_sha256"] != hashlib.sha256(data).hexdigest():
        raise SystemExit("raw rankings do not match the recorded retrieval run")
    return _read_object(data)
