import unittest
from src.evaluation.ragas_eval.core import paired_comparison
from .ragas_fixtures import row


class OracleE4PairTests(unittest.TestCase):
    def test_pair_on_id_not_row_order(self):
        r = [row('q2', 'e4_top5', score=.4), row('q1', 'oracle', score=.5),
             row('q2', 'oracle', score=.6), row('q1', 'e4_top5', score=.8)]
        result = paired_comparison(r)['faithfulness']
        self.assertAlmostEqual(result['mean'], .05)
        self.assertEqual(result['n'], 2)

    def test_abstained_pair_excluded(self):
        result = paired_comparison([row(), row(condition='e4_top5', status='insufficient_evidence')])
        self.assertEqual(result['faithfulness']['n'], 0)
        self.assertEqual(result['faithfulness']['n_excluded_pairs'], 1)
