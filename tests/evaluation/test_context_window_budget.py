from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import context_budget_audit


class ContextWindowBudgetTests(unittest.TestCase):
    def test_remaining_margin_includes_reserved_output_budget(self) -> None:
        row = context_budget_audit(prompt_tokens=4000, baseline_prompt_tokens=4000)
        self.assertEqual(row["remaining_context_margin"], 3168)
        self.assertTrue(row["output_budget_fits_context_after_prompt"])
        self.assertFalse(row["input_truncated"])


if __name__ == "__main__":
    unittest.main()
