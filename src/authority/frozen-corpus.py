"""P0 Frozen eval corpus generation and versioning.

Per DELIVERY.md:
  "Freeze corpus versions, gold source revisions, questions, parameters
   and thresholds before optimization."

Produces:
- research/eval-corpus/frozen/v1/ questions.json
- research/eval-corpus/frozen/v1/ documents.json
- research/eval-corpus/frozen/v1/ split.json (with split hash)
- research/eval-corpus/frozen/v1/ manifest.json (checksums + metadata)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def frozen_corpus_hash(data: bytes) -> str:
    """SHA-256 of frozen corpus data."""
    return "c:" + hashlib.sha256(data).hexdigest()[:16]


def build_and_freeze_corpus(output_dir: Optional[str] = None) -> dict:
    """Build corpus, freeze it, and return manifest."""
    if output_dir is None:
        output_dir = "/home/kos/agent-ui-test/research/eval-corpus/frozen/v1"

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Import corpus builder
    sys.path.insert(0, "/home/kos/agent-ui-test")
    from src.authority.corpus import build_corpus, save_corpus

    # Build
    corpus = build_corpus("/home/kos/agent-ui-test/research")

    # Save to frozen location
    save_corpus(corpus, str(out))

    # Compute manifest
    manifest = {
        "version": "1",
        "generated_at": "frozen",
        "total_questions": len(corpus.questions),
        "total_documents": len(corpus.documents),
        "split": corpus.split,
        "stratified_counts": corpus.stratified_counts,
        "files": {},
        "hashes": {}
    }

    for fname in ["questions.json", "documents.json", "split.json"]:
        fpath = out / fname
        if fpath.exists():
            data = fpath.read_bytes()
            manifest["files"][fname] = str(fpath.relative_to(out))
            manifest["hashes"][fname] = frozen_corpus_hash(data)

    # Overall corpus hash
    manifest["corpus_hash"] = frozen_corpus_hash(
        json.dumps(manifest["hashes"], sort_keys=True).encode()
    )

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return manifest


def verify_frozen_corpus(manifest_path: Optional[str] = None) -> bool:
    """Verify current frozen corpus matches the manifest."""
    if manifest_path is None:
        manifest_path = "/home/kos/agent-ui-test/research/eval-corpus/frozen/v1/manifest.json"

    manifest = json.loads(Path(manifest_path).read_text())
    all_ok = True

    for fname, expected_hash in manifest.get("hashes", {}).items():
        fpath = Path(manifest_path).parent / fname
        if not fpath.exists():
            print(f"  MISSING: {fname}")
            all_ok = False
            continue
        actual_hash = frozen_corpus_hash(fpath.read_bytes())
        if actual_hash != expected_hash:
            print(f"  MISMATCH: {fname} expected {expected_hash} got {actual_hash}")
            all_ok = False
        else:
            print(f"  OK: {fname} ({expected_hash})")

    print(f"\nCorpus hash: {manifest.get('corpus_hash', 'unknown')}")
    print(f"Status: {'FROZEN ✓' if all_ok else 'DRIFT ✗'}")
    return all_ok


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "freeze"

    if action == "freeze":
        manifest = build_and_freeze_corpus()
        print(f"Frozen corpus manifest at: research/eval-corpus/frozen/v1/manifest.json")
        print(f"Corpus hash: {manifest['corpus_hash']}")
    elif action == "verify":
        ok = verify_frozen_corpus()
        sys.exit(0 if ok else 1)
    else:
        print(f"Usage: frozen-corpus.py [freeze|verify]")
        sys.exit(1)
