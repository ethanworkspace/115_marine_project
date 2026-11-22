import unittest

from src.evaluation.phase20_protocol import EDGE_WEIGHTS, QUALITY_WEIGHTS


class SelectionWeightsTests(unittest.TestCase):
    def test_quality_and_edge_weights_are_frozen_70_30(self):
        self.assertAlmostEqual(sum(QUALITY_WEIGHTS.values()), 0.70)
        self.assertAlmostEqual(sum(EDGE_WEIGHTS.values()), 0.30)


if __name__ == "__main__":
    unittest.main()
