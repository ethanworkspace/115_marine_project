import unittest

from src.evaluation.phase20_protocol import CATEGORIES


class CategoryBalanceTests(unittest.TestCase):
    def test_six_categories_are_fixed(self):
        self.assertEqual(len(CATEGORIES), 6)
        self.assertEqual(CATEGORIES.count("Calculation"), 1)


if __name__ == "__main__":
    unittest.main()
