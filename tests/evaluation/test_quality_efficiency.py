import unittest
from src.evaluation.generation_models.core import stats

class QualityEfficiencyTests(unittest.TestCase):
    def test_missing_measurement_is_null(self): self.assertIsNone(stats([None])['mean'])
    def test_latency_descriptive(self): self.assertEqual(stats([1,3])['median'],2)
