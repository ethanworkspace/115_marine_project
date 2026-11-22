import unittest

from src.evaluation.phase20_protocol import scope_change


class ScopeChangeDisclosureTests(unittest.TestCase):
    def test_report_never_claims_five_model_completion(self):
        scope = scope_change()
        self.assertEqual(scope["original_proposal_model_count"], 5)
        self.assertEqual(scope["actual_comparison_model_count"], 4)
        self.assertFalse(scope["five_model_comparison_completed"])


if __name__ == "__main__":
    unittest.main()
