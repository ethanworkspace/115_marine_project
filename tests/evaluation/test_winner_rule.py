import unittest

from src.evaluation.phase20_protocol import choose_winner


class WinnerRuleTests(unittest.TestCase):
    def test_ineligible_or_missing_score_never_produces_winner(self):
        rows = [{"final_selection_eligible": False, "primary_score": 0.8} for _ in range(4)]
        self.assertIsNone(choose_winner(rows, global_ready=True))
        self.assertIsNone(choose_winner(rows, global_ready=False))


if __name__ == "__main__":
    unittest.main()
