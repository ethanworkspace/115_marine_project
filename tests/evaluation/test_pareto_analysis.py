import unittest
from src.evaluation.generation_models.core import pareto

class ParetoTests(unittest.TestCase):
    def test_tradeoff_keeps_both(self):
        p=[dict(generator='a',primary_eligible=True,q=.9,t=5),dict(generator='b',primary_eligible=True,q=.8,t=1)]
        self.assertEqual(pareto(p,{'q':'max','t':'min'})['non_dominated'],['a','b'])
    def test_dominated_and_conflict_excluded(self):
        p=[dict(generator='a',primary_eligible=True,q=.9,t=1),dict(generator='b',primary_eligible=True,q=.8,t=2),dict(generator='conflict',primary_eligible=False,q=1,t=0)]
        r=pareto(p,{'q':'max','t':'min'}); self.assertEqual(r['non_dominated'],['a']); self.assertEqual(r['excluded'],['conflict'])
