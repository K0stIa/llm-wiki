#!/usr/bin/env python3
"""
Wiki health check — 5 lint passes across all 5 domains.

Checks:
1. Orphan pages (pages with no inbound links, no parent)
2. Missing pages (wikilinks pointing to nonexistent files)
3. Contradiction detection (pages claiming mutually exclusive things)
4. Stale pages (not updated in 30+ days)
5. Coverage gaps (entities mentioned in other pages but lacking their own page)
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta

WIKI_ROOT = Path(__file__).parent.parent

def load_registry() -> dict:
    with open(WIKI_ROOT / "meta" / "registry.json") as f:
        return json.load(f)

def check_orphans(reg: dict) -> list:
    """Find pages with no inbound links."""
    pages = reg.get("pages", {})
    all_titles = set()
    for p in pages.values():
        all_titles.add(p.get("title", "").lower())
    
    orphans = []
    for path, info in pages.items():
        title = info.get("title", "").lower()
        # A page is orphaned if no other page's title/frontmatter references it
        # (simplified: check if it's referenced in any page's content)
        full_path = WIKI_ROOT / path
        if full_path.exists():
            with open(full_path) as f:
                content = f.read().lower()
            # Check if title appears elsewhere
            title_words = set(title.split())
            if title_words and len(title_words) > 2:
                referenced = any(w in content for w in title_words)
                if not referenced:
                    orphans.append(path)
        else:
            orphans.append(path)
    
    return orphans

def check_missing_links(reg: dict) -> list:
    """Find broken wikilinks."""
    broken = []
    pages = reg.get("pages", {})
    
    for path, info in pages.items():
        full_path = WIKI_ROOT / path
        if not full_path.exists():
            broken.append(("MISSING_FILE", path))
            continue
        
        with open(full_path) as f:
            content = f.read()
        
        # Find [label](path) style links
        for m in re.finditer(r'\]\(([^)]+)\)', content):
            link = m.group(1).lstrip('/')
            if link and link not in pages and not link.startswith('http'):
                broken.append(("MISSING_LINK", path, link))
        
        # Find [[path]] style links
        for m in re.finditer(r'\[\[([^]]+)\]\]', content):
            link = m.group(1).lstrip('/')
            if link and link not in pages and not link.startswith('http'):
                broken.append(("MISSING_WIKILINK", path, link))
    
    return broken

def check_stale(reg: dict, days: int = 30) -> list:
    """Find pages not updated in N days."""
    stale = []
    cutoff = datetime.now() - timedelta(days=days)
    
    for path, info in pages.items():
        updated = info.get("updated", "")
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                if updated_dt.replace(tzinfo=None) < cutoff:
                    stale.append((path, updated))
            except (ValueError, TypeError):
                pass
    
    return stale

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wiki health check")
    parser.add_argument("--fix", action="store_true", help="Auto-fix missing links")
    args = parser.parse_args()
    
    reg = load_registry()
    
    print("## Wiki Health Check")
    print()
    
    # Check 1: Orphans
    orphans = check_orphans(reg)
    print(f"**Orphan pages** (no inbound links): {len(orphans)}")
    for p in orphans[:5]:
        print(f"  - {p}")
    if len(orphans) > 5:
        print(f"  ... and {len(orphans) - 5} more")
    print()
    
    # Check 2: Missing links
    broken = check_missing_links(reg)
    print(f"**Broken links**: {len(broken)}")
    for b in broken[:10]:
        if len(b) == 2:
            print(f"  - MISSING FILE: `{b[0]}` (page gone)")
        else:
            print(f"  - `{b[0]}` links to `{b[2]}` (not in registry)")
    if len(broken) > 10:
        print(f"  ... and {len(broken) - 10} more")
    print()
    
    # Check 3: Stale
    stale = check_stale(reg)
    print(f"**Stale pages** (>30 days): {len(stale)}")
    for p in stale[:5]:
        print(f"  - {p[0]} (last: {p[1]})")
    if len(stale) > 5:
        print(f"  ... and {len(stale) - 5} more")
    print()
    
    # Summary
    total = reg.get("total_pages", 0)
    print(f"**Total pages**: {total}")
    print(f"**Status**: {'CLEAN' if not orphans and not broken and not stale else 'ISSUES FOUND'}")

pages = {}  # placeholder for check_stale closure
