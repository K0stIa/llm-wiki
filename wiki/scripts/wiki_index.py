#!/usr/bin/env python3
"""
Index builder — scans wiki/ pages, updates registry.json and index.md.

Run after any page creation, update, or deletion to keep the registry in sync.
The extension's auto-rebuild is the normal path; this is for manual sync.

Usage:
  python3 wiki_index.py --full
  python3 wiki_index.py --scan
"""

import json
import re
from pathlib import Path
from datetime import datetime

WIKI_ROOT = Path(__file__).parent.parent
DOMAINS = ["wiki_rules", "wiki_domain", "wiki_memory", "wiki_insights", "wiki_sources"]

def scan_pages() -> dict:
    """Scan all wiki domains, return page metadata dict."""
    pages = {}
    
    for domain in DOMAINS:
        domain_path = WIKI_ROOT / domain
        if not domain_path.exists():
            continue
        
        for md_file in sorted(domain_path.rglob("*.md")):
            rel_path = md_file.relative_to(WIKI_ROOT)
            path_str = str(rel_path)
            
            # Read frontmatter
            page_type = "concept"  # default
            sources = []
            title = md_file.stem.replace("-", " ").title()
            created = datetime.now().isoformat()
            
            with open(md_file) as f:
                lines = f.readlines()
            
            in_fm = False
            for line in lines:
                if line.strip() == "---":
                    in_fm = not in_fm
                    continue
                if in_fm:
                    m = re.match(r'^type:\s*(.+)$', line.strip())
                    if m:
                        page_type = m.group(1).strip()
                    m = re.match(r'^title:\s*(.+)$', line.strip())
                    if m:
                        title = m.group(1).strip()
                    m = re.match(r'^created:\s*(.+)$', line.strip())
                    if m:
                        created = m.group(1).strip()
                    m = re.match(r'^sources:\s*\[(.+)\]', line.strip())
                    if m:
                        sources = [s.strip().strip('"\'') for s in m.group(1).split(',')]
            
            pages[path_str] = {
                "type": page_type,
                "title": title,
                "updated": created,
                "sources": sources,
                "domain": domain
            }
    
    return pages

def update_registry() -> dict:
    """Scan pages and write registry.json."""
    pages = scan_pages()
    
    # Add index pages if missing
    for domain in DOMAINS:
        idx_path = f"{domain}/index.md"
        if idx_path not in pages:
            pages[idx_path] = {
                "type": "index",
                "title": domain.replace("wiki_", "").title(),
                "updated": datetime.now().isoformat(),
                "sources": [],
                "domain": domain
            }
    
    reg = {
        "version": "1.0.0",
        "domains": DOMAINS,
        "pages": pages,
        "total_pages": len(pages)
    }
    
    with open(WIKI_ROOT / "meta" / "registry.json", "w") as f:
        json.dump(reg, f, indent=2)
    
    return reg

def generate_index_md(reg: dict) -> str:
    """Generate human-readable index.md."""
    lines = ["# Wiki Index", ""]
    
    for domain in DOMAINS:
        domain_pages = [(p, i) for p, i in reg["pages"].items() 
                       if p.startswith(domain + "/") and i.get("type") != "index"]
        if domain_pages:
            domain_name = domain.replace("wiki_", "").title()
            lines.append(f"## {domain_name}")
            lines.append("")
            for path, info in sorted(domain_pages, key=lambda x: x[1].get("title", "")):
                title = info.get("title", path)
                page_type = info.get("type", "?")
                updated = info.get("updated", "?")[:10]
                lines.append(f"- [{title}](wiki/{path}) (`{page_type}`, {updated})")
            lines.append("")
    
    return "\n".join(lines)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wiki index builder")
    parser.add_argument("--full", action="store_true", help="Full scan + write")
    parser.add_argument("--scan", action="store_true", help="Just scan, don't write")
    args = parser.parse_args()
    
    reg = update_registry() if args.full else {"pages": scan_pages(), "total_pages": len(scan_pages())}
    
    print(f"Registry: {reg['total_pages']} pages across {len(reg['domains'])} domains")
    
    if args.full:
        # Write index.md
        idx_path = WIKI_ROOT / "meta" / "index.md"
        with open(idx_path, "w") as f:
            f.write(generate_index_md(reg))
        print(f"Wrote index to {idx_path}")
    
    # Print page count per domain
    for domain in DOMAINS:
        count = sum(1 for p in reg["pages"] if p.startswith(domain + "/"))
        print(f"  {domain}: {count} pages")

if __name__ == "__main__":
    main()
