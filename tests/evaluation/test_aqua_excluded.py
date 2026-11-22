import unittest

from src.evaluation.phase20_protocol import scope_change


class AquaExcludedTests(unittest.TestCase):
    def test_aqua_never_enters_comparison(self):
        scope = scope_change()
        self.assertFalse(scope["aqua7b_included"])
        self.assertEqual(scope["exclusion_reason"], "revised experimental scope")
        self.assertFalse(scope["aqua7b_downloaded"])
        self.assertFalse(scope["proxy_model_created"])


if __name__ == "__main__":
    unittest.main()
