import unittest

from src.evaluation.grounded.pipeline import ALLOWED_QUERY_STYLES, STYLE_DIFFICULTY


class QueryStyleTests(unittest.TestCase):
    def test_three_required_styles_are_supported(self):
        self.assertEqual(set(ALLOWED_QUERY_STYLES), {"direct", "paraphrase", "contextual"})
        self.assertEqual(set(STYLE_DIFFICULTY), set(ALLOWED_QUERY_STYLES))
        self.assertEqual(STYLE_DIFFICULTY["direct"], "easy")
        self.assertEqual(STYLE_DIFFICULTY["contextual"], "medium")


if __name__ == "__main__":
    unittest.main()

