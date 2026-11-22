from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import context_budget_audit


class NoInputTruncationTests(unittest.TestCase):
    def test_shorter_runtime_prompt_count_is_flagged(self) -> None:
        row = context_budget_audit(prompt_tokens=7900, baseline_prompt_tokens=8100)
        self.assertTrue(row["input_truncated"])

    def test_equal_prompt_count_is_not_flagged(self) -> None:
        row = context_budget_audit(prompt_tokens=8100, baseline_prompt_tokens=8100)
        self.assertFalse(row["input_truncated"])

    def test_unobservable_prompt_count_remains_unknown(self) -> None:
        row = context_budget_audit(prompt_tokens=None, baseline_prompt_tokens=1000)
        self.assertIsNone(row["input_truncated"])


if __name__ == "__main__":
    unittest.main()
