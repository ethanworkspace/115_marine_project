import unittest
from src.evaluation.edge.exec19b_r2 import latency_comparison

class CrossPhase(unittest.TestCase):
    def test_descriptive_difference(self):
        r=latency_comparison({'median':2000},{'median':1500})
        self.assertEqual(r['difference_ms'],500)
        self.assertIn('not exclusively retrieval',r['interpretation'])
    def test_missing_not_imputed(self):
        self.assertIsNone(latency_comparison({'median':None},{'median':1})['difference_ms'])
