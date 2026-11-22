import unittest
from src.evaluation.generation_models.core import stats, total_latency_or_none

class ModelLatencyTests(unittest.TestCase):
    def test_no_guessed_memory(self): self.assertEqual(stats([None])['n'],0)
    def test_percentile(self): self.assertEqual(stats([1,2,3])['p95'],2.9)
    def test_nan_excluded(self): self.assertEqual(stats([float('nan'),1])['mean'],1)
    def test_missing_attempt_latency_is_unknown(self): self.assertIsNone(total_latency_or_none([None,2]))
    def test_known_retry_latency_summed(self): self.assertEqual(total_latency_or_none([2,3]),5)
    def test_empty_latency_not_zero(self): self.assertIsNone(total_latency_or_none([]))
