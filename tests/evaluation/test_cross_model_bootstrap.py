import unittest
from .phase17_fixtures import row
from src.evaluation.generation_models.core import pair_compare

class CrossModelBootstrapTests(unittest.TestCase):
    def test_fixed_seed_and_identical_recompute(self):
        a,b=[row('a'),row('b')],[row('a',score=.8),row('b',score=.6)]
        x=pair_compare(a,b); self.assertEqual(x,pair_compare(a,b)); self.assertEqual(x['faithfulness']['seed'],17017)
    def test_zero_difference_not_superior(self):
        x=pair_compare([row()],[row()]); self.assertFalse(x['faithfulness']['clearly_separated_on_silver_sample'])
