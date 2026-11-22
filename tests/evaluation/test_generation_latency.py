import unittest

from src.evaluation.generation.evaluation import _stats
from src.evaluation.generation.ollama import GENERATION_OPTIONS


class GenerationLatencyTests(unittest.TestCase):
    def test_generation_parameters_are_fixed_and_latency_summary_is_reproducible(self):
        self.assertEqual(GENERATION_OPTIONS["temperature"], 0)
        self.assertEqual(_stats([1, 2, 3])["median"], 2)
        self.assertEqual(_stats([1, 2, 3])["p95"], 3)
        self.assertIsNone(_stats([])["mean"])


if __name__ == "__main__":
    unittest.main()
