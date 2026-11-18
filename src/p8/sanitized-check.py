#!/usr/bin/env python3
"""
P8: Sanitization check for release artifacts.

Ensures no private corpus text (questions, answers, gold evidence) appears
in any documentation or spec files outside the frozen corpus directory.

Run before release: `python3 src/p8/sanitized-check.py`

Returns 0 on clean, 1 on FAIL, 2 on unverifiable (corpus or artifacts missing).
"""

import json
import sys
from pathlib import Path


def get_corpus_text() -> tuple[set, bool]:
    """Load all text from the frozen corpus.

    Returns (corpus_text_set, was_readable). If corpus is missing or unreadable,
    returns (set(), False) — caller must treat this as UNVERIFIABLE.
    """
    corpus_path = Path("research/eval-corpus/frozen/v1")
    corpus = set()
    try:
        manifest = json.loads((corpus_path / "manifest.json").read_text())
        if not isinstance(manifest, dict) or str(manifest.get("version")) != "1":
            return set(), False
        for filename, field in (("questions.json", "query"), ("documents.json", "body")):
            rows = json.loads((corpus_path / filename).read_text())
            if not isinstance(rows, list) or not rows:
                return set(), False
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get(field), str):
                    return set(), False
                # A standalone field must be detected without its title/source suffix.
                text = row[field].strip()
                if text:
                    corpus.add(text)
    except (OSError, UnicodeError, ValueError):
        return set(), False
    return corpus, bool(corpus)


def discover_artifacts() -> list[Path]:
    """Discover all target artifact files to scan.

    Returns sorted list of Path objects. If empty, caller must treat
    as UNVERIFIABLE (no artifacts to scan).
    """
    artifacts = []
    # Explicit release-code inventory. Frozen evaluation inputs and .git history
    # are not release artifacts; a separately staged release must exclude them.
    # Do not limit source scanning to documentation extensions.
    for folder in ("src", "specs/wiki-system", "tests"):
        for p in Path(folder).rglob("*"):
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            if p.is_symlink():
                raise ValueError(f"release artifact symlink not classified: {p}")
            if p.is_file():
                artifacts.append(p)
    for p in Path(".").iterdir():
        if p.name.startswith(".") or not p.is_file():
            continue
        if p.is_symlink():
            raise ValueError(f"release artifact symlink not classified: {p}")
        artifacts.append(p)

    return sorted(set(artifacts))


def check_file(filepath: Path, corpus: set) -> tuple[int, list[str]]:
    """Check a file for private corpus text.

    Returns (count_of_leaks, list_of_file_paths_with_leaks).
    Never prints full leaked lines — only filenames to avoid exposing
    private corpus text in public reports.
    """
    content = filepath.read_text()
    for text in corpus:
        if text in content:
            return 1, [str(filepath)]
    return 0, []


def main():
    corpus, was_readable = get_corpus_text()
    if not was_readable:
        print("UNVERIFIABLE: corpus frozen-v1/ manifest missing or unreadable.")
        print("Cannot confirm sanitization — corpus may not be frozen.")
        return 2

    try:
        artifacts = discover_artifacts()
    except (OSError, ValueError) as error:
        print(f"UNVERIFIABLE: artifact inventory: {error}")
        return 2
    if not artifacts:
        print(f"UNVERIFIABLE: 0 artifact files found to scan. No corpus to check against.")
        print("Cannot confirm sanitization — no target files exist.")
        return 2

    print(f"Scanning {len(artifacts)} artifact file(s) against {len(corpus)} corpus items...")

    leak_count = 0
    leak_files = set()

    for p in artifacts:
        try:
            count, paths = check_file(p, corpus)
        except (OSError, UnicodeError):
            print(f"UNVERIFIABLE: artifact could not be read: {p}")
            return 2
        if count:
            leak_count += count
            leak_files.update(paths)

    if leak_count:
        print(f"FAIL: {leak_count} corpus text leaks in {len(leak_files)} file(s):")
        for f in sorted(leak_files):
            print(f"  {f}")
        print("(Leaked content not printed here to avoid exposing private corpus text.)")
        return 1

    print(f"OK: {len(corpus)} corpus items checked, 0 leaks across {len(artifacts)} files scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
