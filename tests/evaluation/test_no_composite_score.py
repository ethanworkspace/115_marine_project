import unittest
from src.evaluation.generation_models.core import pareto

class NoCompositeTests(unittest.TestCase):
    def test_no_weighted_score(self):
        r=pareto([],{'q':'max','t':'min'})
        self.assertNotIn('winner',r); self.assertNotIn('weighted_score',r)
