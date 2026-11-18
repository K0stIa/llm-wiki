#!/usr/bin/env python3
"""Score saved rankings against gold IDs. Does not invoke a model."""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def metrics(queries, records):
    by_id = {q['id']: q for q in queries}
    assert len(by_id) == len(queries), 'Duplicate query IDs'
    assert len(records) == len(queries), 'Missing or extra query results'
    assert {r['query'] for r in records} == set(by_id), 'Mismatched query IDs'
    positive, negatives = [], []
    for record in records:
        query = by_id[record['query']]
        ids = record['ids'][:5]
        assert len(ids) == len(set(ids)), 'Duplicate ranked page IDs'
        gold = set(query['gold'])
        if not gold:
            negatives.append(bool(ids))
            continue
        hits = len(gold.intersection(ids))
        rank = next((i for i, page in enumerate(ids, 1) if page in gold), None)
        positive.append({'query': query['id'], 'kind': query['kind'], 'recall': hits / len(gold),
                         'complete': hits == len(gold), 'reciprocal_rank': 1 / rank if rank else 0})
    return {
        'positive_queries': len(positive), 'negative_queries': len(negatives),
        'macro_recall_at_5': statistics.mean(p['recall'] for p in positive),
        'all_required_at_5': statistics.mean(p['complete'] for p in positive),
        'mrr_at_5': statistics.mean(p['reciprocal_rank'] for p in positive),
        'negative_queries_with_any_result': sum(negatives),
        'median_ms': statistics.median(r['elapsed_ms'] for r in records),
        'incomplete_queries': [p['query'] for p in positive if not p['complete']],
        'by_kind_recall': {kind: statistics.mean(p['recall'] for p in positive if p['kind'] == kind)
                           for kind in sorted({p['kind'] for p in positive})},
    }


def main():
    fixture = json.loads((ROOT / 'research/fixture.json').read_text())
    challenge = '--challenge' in sys.argv
    queries = json.loads((ROOT / 'research/challenge.json').read_text())['queries'] if challenge else fixture['queries']
    filename = 'challenge-retrieval.json' if challenge else 'retrieval.json'
    raw = json.loads((ROOT / 'research/results' / filename).read_text())
    valid_ids = {d['id'] for d in fixture['documents']}
    assert all(set(r['ids']) <= valid_ids for r in raw['records']), 'Unknown document IDs'
    summary = {engine: metrics(queries, [r for r in raw['records'] if r['engine'] == engine])
               for engine in sorted({r['engine'] for r in raw['records']})}
    output = 'challenge-summary.json' if challenge else 'summary.json'
    (ROOT / 'research/results' / output).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
