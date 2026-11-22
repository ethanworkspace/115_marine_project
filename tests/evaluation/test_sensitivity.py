import unittest

from src.evaluation.phase20_protocol import SENSITIVITY_SPLITS


class SensitivityTests(unittest.TestCase):
    def test_three_predeclared_quality_edge_splits(self):
        self.assertEqual(SENSITIVITY_SPLITS, ((0.60, 0.40), (0.70, 0.30), (0.80, 0.20)))


if __name__ == "__main__":
    unittest.main()
