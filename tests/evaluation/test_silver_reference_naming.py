import unittest
from src.evaluation.ragas_eval.core import METRICS, summarize, pair_inputs
from .ragas_fixtures import row, export_pair


class SilverNamingTests(unittest.TestCase):
    def test_reference_metric_has_silver_name(self):
        self.assertIn('silver_reference_correctness', METRICS)
        self.assertNotIn('answer_correctness', METRICS)
        s = summarize([row()], ci=False)
        self.assertEqual(s['benchmark_type'], 'silver')
        self.assertIn('not human expert', s['metrics'][METRICS[2]]['reference_note'])

    def test_unlabelled_reference_fails(self):
        r = export_pair()
        r[0]['silver_reference'] = False
        with self.assertRaises(ValueError):
            pair_inputs(r, 1)
