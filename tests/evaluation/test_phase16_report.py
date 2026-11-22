import unittest
from src.evaluation.ragas_eval.core import summarize, error_labels
from .ragas_fixtures import row


class Phase16ReportTests(unittest.TestCase):
    def test_no_composite_and_all_metric_counts(self):
        s = summarize([row()], ci=False)
        self.assertNotIn('composite_score', s)
        for m in s['metrics'].values():
            self.assertIn('n_total', m)
            self.assertIn('n_valid', m)
            self.assertIn('n_failed', m)
        self.assertTrue(all(m['judge_based'] for m in s['metrics'].values()))

    def test_threshold_fixed_and_diagnostic_only(self):
        r = row(score=.49)
        self.assertIn('retrieval_hit_generation_low_faithfulness', error_labels(r))
        self.assertIn('retrieval_hit_low_reference_correctness', error_labels(r))
        self.assertEqual(error_labels(row(score=.5)), [])
