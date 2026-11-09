import unittest
from research.score import metrics


class MetricsTests(unittest.TestCase):
    def test_partial_cross_document_hit_is_not_complete(self):
        queries = [{'id': 'a', 'kind': 'cross-document', 'gold': ['one', 'two']},
                   {'id': 'b', 'kind': 'negative', 'gold': []}]
        scored = metrics(queries, [{'query': 'a', 'ids': ['noise', 'one'], 'elapsed_ms': 2},
                                  {'query': 'b', 'ids': [], 'elapsed_ms': 4}])
        self.assertEqual(scored['macro_recall_at_5'], 0.5)
        self.assertEqual(scored['all_required_at_5'], 0)
        self.assertEqual(scored['mrr_at_5'], 0.5)
        self.assertEqual(scored['negative_queries_with_any_result'], 0)

    def test_duplicate_or_missing_results_are_rejected(self):
        queries = [{'id': 'a', 'kind': 'literal', 'gold': ['one']}]
        with self.assertRaises(AssertionError):
            metrics(queries, [])
        with self.assertRaises(AssertionError):
            metrics(queries, [{'query': 'a', 'ids': ['one', 'one'], 'elapsed_ms': 1}])

    def test_only_first_five_results_count(self):
        query = [{'id': 'a', 'kind': 'literal', 'gold': ['one']}]
        scored = metrics(query, [{'query': 'a', 'ids': ['a', 'b', 'c', 'd', 'e', 'one'], 'elapsed_ms': 1}])
        self.assertEqual(scored['macro_recall_at_5'], 0)
        self.assertEqual(scored['mrr_at_5'], 0)


if __name__ == '__main__':
    unittest.main()
