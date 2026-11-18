#!/usr/bin/env python3
"""FTS5 BM25 with OR terms as a diagnostic control, not a production retriever."""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP = set('a an the this that what which how who where when is are was were does do did can could should would i my we our you your to of for on in at by with from and or its it as be have has after before'.split())


def main():
    fixture = json.loads((ROOT / 'research/fixture.json').read_text())
    challenge = '--challenge' in sys.argv
    queries = json.loads((ROOT / 'research/challenge.json').read_text())['queries'] if challenge else fixture['queries']
    filename = 'challenge-retrieval.json' if challenge else 'retrieval.json'
    path = ROOT / 'research/results' / filename
    result = json.loads(path.read_text())
    connection = sqlite3.connect(':memory:')
    connection.execute("CREATE VIRTUAL TABLE pages USING fts5(id UNINDEXED, title, body, tokenize='porter unicode61')")
    for doc in fixture['documents']:
        body = (ROOT / '.cache/comparison/corpus' / (doc['id'] + '.md')).read_text()
        connection.execute('INSERT INTO pages VALUES (?, ?, ?)', (doc['id'], doc['title'], body))
    records = []
    for query in queries:
        terms = sorted({w for w in re.findall(r'\w+', query['query'].lower()) if w not in STOP})
        expression = ' OR '.join('"' + word + '"' for word in terms)
        start = time.perf_counter()
        rows = connection.execute('SELECT id, bm25(pages, 0, 3, 1) FROM pages WHERE pages MATCH ? ORDER BY bm25(pages, 0, 3, 1), id LIMIT 5', (expression,)).fetchall() if terms else []
        records.append({'engine': 'sqlite-fts5-or-control', 'query': query['id'], 'ids': [r[0] for r in rows],
                        'scores': [r[1] for r in rows], 'elapsed_ms': (time.perf_counter() - start) * 1000})
    connection.close()
    result['versions']['sqlite'] = sqlite3.sqlite_version
    result['records'] = [r for r in result['records'] if r['engine'] != 'sqlite-fts5-or-control'] + records
    path.write_text(json.dumps(result, indent=2) + '\n')
    print('Saved SQLite OR-query control for', len(records), 'queries')


if __name__ == '__main__':
    main()
