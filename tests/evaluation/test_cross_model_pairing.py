import unittest
from .phase17_fixtures import row
from src.evaluation.generation_models.core import pair_compare

class CrossModelPairingTests(unittest.TestCase):
    def test_missing_question_fails(self):
        with self.assertRaises(ValueError): pair_compare([row('a')],[row('b')])
    def test_conflicted_judge_excluded_but_deterministic_retained(self):
        r=pair_compare([row()],[row(score=.7)],primary_judge=False)
        self.assertEqual(r['faithfulness']['status'],'excluded_judge_conflict')
        self.assertAlmostEqual(r['citation_recall']['mean'],.2)
