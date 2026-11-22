import unittest
from src.evaluation.ragas_eval.core import retrieval_split, error_labels
from .ragas_fixtures import row


class RetrievalHitSplitTests(unittest.TestCase):
    def test_hit_miss_and_answered_cohort(self):
        r = [row('a', 'e4_top5'), row('b', 'e4_top5', hit=False), row('c', 'e4_top5', status='insufficient_evidence')]
        s = retrieval_split(r)
        self.assertEqual(s['hit']['n_questions'], 2)
        self.assertEqual(s['miss']['n_questions'], 1)
        self.assertEqual(s['hit_and_answered']['n_questions'], 1)
        self.assertIn('answered_without_required_evidence', error_labels(r[1]))
        self.assertNotIn('hallucination', error_labels(r[1]))
        self.assertIn('false_abstention_candidate', error_labels(r[2]))
