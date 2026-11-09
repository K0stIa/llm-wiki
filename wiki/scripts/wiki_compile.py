#!/usr/bin/env python3
"""
Context compiler — reads the wiki index, sorts by priority, truncates to a token budget.

Produces a "compiled context" snippet that can be injected into a session's system prompt.
This is the mechanism that makes "retrieval at point-of-use" reliable past 100+ pages.

Usage:
  python3 wiki_compile.py --budget 2000 --domains wiki_rules,wiki_domain
  python3 wiki_compile.py --budget 2000 --domain wiki_memory --all
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

WIKI_ROOT = Path(__file__).parent.parent

@dataclass
class CompiledPage:
    path: str
    title: str
    content: str  # trimmed to budget
    priority: int  # 1=highest (rules loaded first)
    domain: str

def load_registry() -> dict:
    with open(WIKI_ROOT / "meta" / "registry.json") as f:
        return json.load(f)

def page_token_count(content: str) -> int:
    """Approximate token count: words * 1.3 (typical token/word ratio)."""
    return int(len(content.split()) * 1.3)

def compile_context(budget: int, domains: list[str] = None, all_domains: bool = False) -> str:
    """Read wiki index, sort by priority, truncate to budget, produce injected text."""
    reg = load_registry()
    pages = reg.get("pages", {})
    
    # Priority assignment by domain
    domain_priority = {
        "wiki_rules": 1,      # Always loaded first
        "wiki_memory": 2,     # Session memory
        "wiki_domain": 3,     # Domain knowledge
        "wiki_insights": 4,   # Active insights
        "wiki_sources": 5,    # Sources (never auto-loaded)
    }
    
    # Filter pages
    candidates = []
    for path, info in pages.items():
        page_domain = path.split("/")[0]
        if all_domains or page_domain in (domains or []):
            # Skip index pages (they are navigational, not content)
            if info.get("type") == "index":
                continue
            candidates.append({
                "path": path,
                "title": info.get("title", path),
                "priority": domain_priority.get(page_domain, 99),
                "type": info.get("type", "?")
            })
    
    # Sort: highest priority first, then by title (deterministic)
    candidates.sort(key=lambda c: (c["priority"], c["title"]))
    
    # Compile to budget
    total_tokens = 0
    result = []
    
    for c in candidates:
        full_path = WIKI_ROOT / c["path"]
        if not full_path.exists():
            continue
        
        with open(full_path) as f:
            content = f.read()
        
        # Skip frontmatter
        in_fm = False
        body_lines = []
        for line in content.split('\n'):
            if line.strip() == "---":
                in_fm = not in_fm
                continue
            if not in_fm:
                body_lines.append(line)
        body = '\n'.join(body_lines).strip()
        
        if not body:
            continue
        
        tokens = page_token_count(body)
        if total_tokens + tokens > budget:
            # Truncate: take first 300 chars
            truncated = body[:300] + "..."
            tokens = page_token_count(truncated)
            body = truncated
        
        result.append(f"## {c['title']} ({c['path']})\n{body}\n")
        total_tokens += tokens
    
    return f"## Compiled Wiki Context ({total_tokens} tokens)\n\n{''.join(result)}"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Context compile from wiki index")
    parser.add_argument("--budget", type=int, default=2000, help="Token budget")
    parser.add_argument("--domains", nargs="*", help="Domains to include")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    
    output = compile_context(args.budget, args.domains, args.all)
    print(output)

if __name__ == "__main__":
    main()
