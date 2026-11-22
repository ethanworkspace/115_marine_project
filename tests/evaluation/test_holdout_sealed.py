import unittest

from src.evaluation.phase20_protocol import holdout_integrity


class HoldoutSealedTests(unittest.TestCase):
    def test_holdout_ids_never_appear_in_evaluation_ids(self):
        self.assertTrue(holdout_integrity(["s1"], ["h1"], ["s1"]))
        self.assertFalse(holdout_integrity(["s1"], ["h1"], ["h1"]))


if __name__ == "__main__":
    unittest.main()
