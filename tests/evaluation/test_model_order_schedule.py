import unittest
from src.evaluation.edge.core import MODELS,schedule
class OrderTest(unittest.TestCase):
    def test_exact_rounds(self):
        s=schedule()
        self.assertEqual([r['model'] for r in s[:4]],list(MODELS))
        self.assertEqual([r['model'] for r in s[4:8]],list(MODELS[1:]+MODELS[:1]))
        self.assertEqual([r['model'] for r in s[8:]],list(MODELS[2:]+MODELS[:2]))
