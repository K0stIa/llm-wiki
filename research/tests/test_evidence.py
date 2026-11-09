"""Offline checks for the published synthetic evidence. No models/network required."""
import hashlib
import json
import unittest
from pathlib import Path
from research.score import metrics

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / name).read_text())


class EvidenceTests(unittest.TestCase):
    def test_fixture_and_gold_ids_are_consistent(self):
        fixture = load('fixture.json')
        ids = {d['id'] for d in fixture['documents']}
        self.assertEqual(len(ids), len(fixture['documents']))
        for query in fixture['queries'] + load('challenge.json')['queries']:
            self.assertLessEqual(set(query['gold']), ids)
        self.assertEqual(sum(not q['gold'] for q in fixture['queries']), 2)

    def test_saved_rankings_match_fixtures_and_summaries(self):
        fixture = load('fixture.json')
        valid_ids = {d['id'] for d in fixture['documents']}
        for prefix, queries in [('', fixture['queries']), ('challenge-', load('challenge.json')['queries'])]:
            with self.subTest(suite=prefix):
                raw, summary = load('results/' + prefix + 'retrieval.json'), load('results/' + prefix + 'summary.json')
                self.assertEqual(raw['fixture_sha256'], hashlib.sha256((ROOT / 'fixture.json').read_bytes()).hexdigest())
                if prefix:
                    self.assertEqual(raw['challenge_sha256'], hashlib.sha256((ROOT / 'challenge.json').read_bytes()).hexdigest())
                self.assertEqual(set(summary), {r['engine'] for r in raw['records']})
                for record in raw['records']:
                    self.assertLessEqual(set(record['ids']), valid_ids)
                for engine in summary:
                    self.assertEqual(summary[engine], metrics(queries, [r for r in raw['records'] if r['engine'] == engine]))

    def test_semantic_runs_record_the_actual_model_and_false_positives(self):
        raw = load('results/retrieval.json')
        config = raw['vector_configuration']
        self.assertTrue(config['cpu_only'])
        self.assertFalse(config['reranking'])
        self.assertEqual(config['embed_result']['chunksEmbedded'], 24)
        self.assertEqual(config['embed_result']['errors'], 0)
        self.assertEqual(len(config['model_sha256']), 1)
        summary = load('results/summary.json')
        self.assertEqual(summary['qmd-vector']['negative_queries_with_any_result'], 2)

    def test_main_live_cases_have_both_candidates_and_recorded_calls(self):
        records = load('results/live.json')
        for candidate in ['zosma', 'nvk']:
            for case in ['q05', 'q09', 'q12', 'q21']:
                matching = [r for r in records if r['candidate'] == candidate and r['case'] == case]
                self.assertTrue(matching)
                self.assertTrue(all(r['exit_code'] == 0 and r['answer'] for r in matching))
        ids = [r['session_id'] for r in records]
        self.assertEqual(len(ids), len(set(ids)), 'Tests must not reuse an old session')

    def test_persistence_and_child_evidence_are_distinct_from_ranking_scores(self):
        records = load('results/live.json')
        reloads = [r for r in records if r['case'] in ['reload', 'read-child']]
        self.assertEqual({r['case'] for r in reloads}, {'reload', 'read-child'})
        self.assertTrue(all('amber-orbit-592' in r['answer'] for r in reloads))
        child = load('results/child.json')
        self.assertIsNone(child['error'])
        self.assertTrue(child['read_original'] and child['wrote_child_page'] and child['marker_preserved'])

    def test_write_loss_and_single_writer_control_are_both_reported(self):
        report = load('results/concurrency.json')
        cases = {c['mode']: c for c in report['zosma']}
        self.assertEqual(cases['distinct-pages']['surviving_markers'], 64)
        self.assertEqual(cases['same-page']['surviving_markers'], 1)
        capture = cases['capture']
        self.assertEqual(capture['acknowledged_writes'], 96)
        self.assertLess(capture['unique_ids'], capture['acknowledged_writes'])
        self.assertEqual(capture['unique_ids'], capture['surviving_markers'])
        self.assertEqual(report['single_writer_control']['unique_ids'], 96)
        self.assertIn('11 passed, 0 failed', report['nvk_upstream_session_regression'])

    def test_public_source_manifest_has_pinned_content(self):
        sources = load('results/sources.json')['sources']
        for source in sources:
            if 'repository' not in source:
                continue
            self.assertEqual(len(source['revision']), 40)
            self.assertTrue(source['files'])
            for item in source['files']:
                if 'sha256' in item:
                    self.assertEqual(len(item['sha256']), 64)
                    self.assertIn(source['revision'], item['url'])


if __name__ == '__main__':
    unittest.main()
