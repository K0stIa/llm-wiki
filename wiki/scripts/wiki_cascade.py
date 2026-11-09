#!/usr/bin/env python3
"""
Cascading update after source ingest.

When a new source is ingested (new entity, concept, or fact),
this script scans the wiki index to find related pages that should be refreshed.
It produces a "cascading update list" — pages that mention related entities/concepts.

Usage:
  python3 wiki_cascade.py --ingest "New article about Qwen3.8 architecture"
  python3 wiki_cascade.py --refresh wiki_domain/agents.md
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

WIKI_ROOT = Path(__file__).parent.parent

@dataclass
class CascadeTarget:
    path: str
    title: str
    reason: str
    priority: int  # 1=highest

def load_registry() -> dict:
    with open(WIKI_ROOT / "meta" / "registry.json") as f:
        return json.load(f)

def scan_for_related(ingest_text: str, max_targets: int = 15) -> list[CascadeTarget]:
    """Find wiki pages that mention entities/concepts referenced in the new source."""
    reg = load_registry()
    pages = reg.get("pages", {})
    
    # Keywords from ingest (simplified: split on non-alpha, lowercase)
    ingest_words = set(w.lower() for w in ingest_text if len(w) > 2)
    
    targets = []
    for path, info in pages.items():
        title = info.get("title", "").lower()
        # Check if any ingest word appears in the title or type
        matched_words = ingest_words & set(title.split())
        if matched_words:
            # Priority based on match quality
            score = len(matched_words) / max(len(ingest_words), 1)
            reason = f"Title matches: {', '.join(matched_words)}"
            priority = int(score * 10) if score > 0.3 else 5
            targets.append(CascadeTarget(path=path, title=info.get("title", path),
                                         reason=reason, priority=priority))
    
    # Sort by priority (lower = higher priority)
    targets.sort(key=lambda t: t.priority)
    return targets[:max_targets]

def refresh_page(path: str) -> str:
    """Read a page and report its structure for cascade decisions."""
    page_path = WIKI_ROOT / path
    if not page_path.exists():
        return f"## Page not found: {path}"
    
    with open(page_path) as f:
        content = f.read()
    
    # Count sections and links
    sections = len([l for l in content.split('\n') if l.strip().startswith('##')])
    links = len([l for l in content.split('\n') if '](/' in l or '[[/' in l])
    return f"## {path}\nSections: {sections} | Links: {links}\n---\n{content[:800]}..."

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cascading update for wiki ingest")
    parser.add_argument("--ingest", help="Text of the newly ingested source")
    parser.add_argument("--refresh", nargs="*", help="Specific pages to refresh")
    parser.add_argument("--max-targets", type=int, default=15)
    args = parser.parse_args()
    
    if args.refresh:
        print("## Refresh targets (explicit):")
        print()
        for p in args.refresh:
            print(refresh_page(p))
            print()
    elif args.ingest:
        targets = scan_for_related(args.ingest, args.max_targets)
        print("## Cascading update list")
        print(f"Source text length: {len(args.ingest)} chars")
        print(f"Pages to refresh: {len(targets)}")
        print()
        for i, t in enumerate(targets, 1):
            print(f"{i}. **{t.title}** (`{t.path}`) — {t.reason}")
        print()
        print("Action: read each target, update if the new source contradicts or adds facts.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
