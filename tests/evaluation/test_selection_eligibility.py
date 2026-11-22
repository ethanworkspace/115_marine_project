import unittest

from src.evaluation.phase20_protocol import selection_eligibility


class SelectionEligibilityTests(unittest.TestCase):
    def test_missing_identity_or_judge_blocks_eligibility(self):
        result = selection_eligibility({"four_models_ready": False, "independent_judge_ready": False})
        self.assertFalse(result["final_selection_eligible"])
        self.assertIn("four_model_identity_verified", result["failed_gates"])
        self.assertIn("independent_judge_available", result["failed_gates"])


if __name__ == "__main__":
    unittest.main()
