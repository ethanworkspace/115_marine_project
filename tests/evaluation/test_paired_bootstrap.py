import unittest
from src.evaluation.ragas_eval.core import bootstrap, paired_comparison
from .ragas_fixtures import row


class PairedBootstrapTests(unittest.TestCase):
    def test_seed_and_iterations_fixed(self):
        a = bootstrap([.1, .2, -.1])
        self.assertEqual(a, bootstrap([.1, .2, -.1]))
        self.assertEqual((a['iterations'], a['seed']), (10000, 16016))

    def test_identical_pairs_zero_interval(self):
        s = paired_comparison([row(), row(condition='e4_top5')])['faithfulness']
        self.assertEqual(s['ci95'], [0, 0])
        self.assertEqual(s['direction'], 'G1 - G0')
