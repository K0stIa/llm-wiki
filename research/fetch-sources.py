#!/usr/bin/env python3
"""Refetch the pinned public sources in results/sources.json, without executing them."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/comparison/source-review'


def main():
    manifest = json.loads((ROOT / 'research/results/sources.json').read_text())
    count = 0
    for source in manifest['sources']:
        repo = source.get('repository')
        if not repo:
            continue  # The gist record contains metadata only, not reused source code.
        prefix = f"https://raw.githubusercontent.com/{repo}/{source['revision']}/"
        for item in source['files']:
            if 'sha256' not in item:
                continue
            relative = Path(item['path'])
            assert not relative.is_absolute() and '..' not in relative.parts
            assert item['url'].startswith(prefix)
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'pi-wiki-comparison'})
            with urllib.request.urlopen(request, timeout=35) as response:
                data = response.read(2_000_001)
            assert len(data) <= 2_000_000, 'Public source exceeded review size bound'
            assert hashlib.sha256(data).hexdigest() == item['sha256'], 'Pinned source content changed'
            target = CACHE / repo.replace('/', '__') / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            count += 1
    print('Verified and cached', count, 'pinned public source files')


if __name__ == '__main__':
    main()
