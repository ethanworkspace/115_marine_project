import unittest

from src.evaluation.phase20_protocol import CONTEXT_PRECISION_WEIGHT, metric_weights


class ContextPrecisionTests(unittest.TestCase):
    def test_context_precision_is_reported_at_zero_weight(self):
        self.assertEqual(CONTEXT_PRECISION_WEIGHT, 0.0)
        self.assertTrue(metric_weights()["context_precision_non_discriminating"])


if __name__ == "__main__":
    unittest.main()
