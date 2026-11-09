#!/usr/bin/env python3
"""
Two-stage wiki recall for multi-agent sessions.

Stage 1: Scan registry for relevant pages → return ranked links (large vault)
         or inline previews (small vault).
Stage 2: Expand specific pages by path.

Usage:
  python3 wiki_recall.py --query "agent architecture"
  python3 wiki_recall.py --query "agent architecture" --expand wiki_domain/agents.md
"""

import json
import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

WIKI_ROOT = Path(__file__).parent.parent

@dataclass
class PageInfo:
    path: str
    title: str
    page_type: str
    score: float
    snippet: str = ""
    content: Optional[str] = None

def load_registry() -> dict:
    reg_path = WIKI_ROOT / "meta" / "registry.json"
    with open(reg_path) as f:
        return json.load(f)

def keyword_score(query: str, text: str) -> float:
    """Simple keyword scoring: word overlap * 100 + partial match bonus."""
    q_words = set(query.lower().split())
    t_words = set(text.lower().split())
    overlap = len(q_words & t_words)
    if overlap == 0:
        return 0.0
    # partial match bonus (substring of any query word in text)
    partial = sum(1 for w in q_words if any(q in text.lower() for q in w))
    return (overlap / max(len(q_words), 1)) * 100 + partial * 5

def recall(query: str, max_results: int = 5, threshold: int = 50) -> list[PageInfo]:
    """Stage 1: scan registry, rank by keyword overlap, return PageInfos."""
    reg = load_registry()
    pages = reg.get("pages", {})
    
    # Build scored list
    scored = []
    for path, info in pages.items():
        # Score against title + any available frontmatter content
        title = info.get("title", "")
        # Read frontmatter for additional scoring
        meta_path = WIKI_ROOT / path
        if meta_path.exists():
            with open(meta_path) as f:
                lines = f.readlines()
            frontmatter = ""
            in_fm = False
            for line in lines:
                if line.strip() == "---":
                    in_fm = not in_fm
                    continue
                if in_fm:
                    frontmatter += line
        else:
            frontmatter = ""
        
        score = keyword_score(query, title + " " + frontmatter)
        if score > 0:
            snippet = title[:80]
            scored.append(PageInfo(path=path, title=title, page_type=info.get("type", "?"),
                                   score=score, snippet=snippet))
    
    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:max_results]

def expand(path: str) -> str:
    """Stage 2: read full page content. Returns page body (after frontmatter)."""
    page_path = WIKI_ROOT / path
    if not page_path.exists():
        return f"## Page not found: {path}"
    
    with open(page_path) as f:
        lines = f.readlines()
    
    in_fm = False
    body_lines = []
    for line in lines:
        if line.strip() == "---":
            in_fm = not in_fm
            continue
        if not in_fm:
            body_lines.append(line)
    
    return "".join(body_lines)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Two-stage wiki recall")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max-results", type=int, default=5, help="Max pages to return")
    parser.add_argument("--expand", nargs="*", help="Expand specific paths")
    parser.add_argument("--threshold", type=int, default=50, help="Small-vault threshold")
    args = parser.parse_args()
    
    reg = load_registry()
    total_pages = reg.get("total_pages", 0)
    is_small = total_pages <= args.threshold
    
    results = recall(args.query, args.max_results)
    
    # Stage 1 output
    print(f"## Wiki Recall (query: \"{args.query}\")")
    print(f"Total pages in registry: {total_pages} (small-vault: {is_small})")
    print()
    
    if args.expand:
        # Stage 2: expand specific pages
        for p in args.expand:
            print(f"### {p}")
            print(expand(p))
            print()
    elif results:
        for i, page in enumerate(results, 1):
            if is_small:
                # Stage 1 inline preview
                content = expand(page.path)
                preview = content[:500].strip()
                print(f"**{i}. {page.title}** ({page.page_type}, score: {page.score:.0f})")
                print(f"Path: `{page.path}`")
                print(f"> {preview}...")
                print()
            else:
                # Stage 1 links only
                print(f"**{i}. [{page.title}](wiki/{page.path})** ({page.page_type}, score: {page.score:.0f})")
                print(f"> {page.snippet}")
                print()
    else:
        print("*No matching pages found.*")

if __name__ == "__main__":
    main()
