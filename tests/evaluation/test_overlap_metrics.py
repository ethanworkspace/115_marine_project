import unittest

from src.evaluation.grounded_baselines import lexical_overlap_bucket


class OverlapMetricTests(unittest.TestCase):
    def test_fixed_bucket_boundaries(self):
        self.assertEqual(lexical_overlap_bucket(0.349999), "low")
        self.assertEqual(lexical_overlap_bucket(0.35), "medium")
        self.assertEqual(lexical_overlap_bucket(0.55), "medium")
        self.assertEqual(lexical_overlap_bucket(0.550001), "high")


if __name__ == "__main__":
    unittest.main()
