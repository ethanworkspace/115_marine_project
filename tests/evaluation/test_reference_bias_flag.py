import unittest
from src.evaluation.validity.core import BIAS


class BiasFlagTest(unittest.TestCase):
    def test_bias_not_expert_truth(self):
        self.assertTrue(BIAS['reference_alignment_bias_possible'])
        self.assertEqual(BIAS['reference_generator'],'Gemma 2 9B')
        self.assertFalse(BIAS['human_expert_verified'])
