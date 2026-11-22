import unittest

from src.evaluation.phase20_protocol import phase21_readiness


class Phase21GateTests(unittest.TestCase):
    def test_phase21_needs_complete_selection_and_eligible_winner(self):
        args = dict(four_models_completed=True, independent_judge_ready=False,
                    all_primary_metrics_complete=False, workbook_complete=True,
                    eligible_winner_exists=False)
        result = phase21_readiness(**args)
        self.assertFalse(result["final_model_selection_ready"])
        self.assertFalse(result["phase21_final_system_ready"])


if __name__ == "__main__":
    unittest.main()
