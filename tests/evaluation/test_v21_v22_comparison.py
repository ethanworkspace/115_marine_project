from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import compare_v21_v22


class V21V22ComparisonTests(unittest.TestCase):
    def test_comparison_labels_budget_only_reliability_change(self) -> None:
        result = compare_v21_v22(
            {"schema_valid_rate": .988, "retry_protocol": {"retry_trigger_count": 2}},
            {"schema_valid_rate": 1.0, "retry_protocol": {"retry_trigger_count": 0}},
        )
        self.assertEqual(result["v2_1_max_output_tokens"], 768)
        self.assertEqual(result["v2_2_max_output_tokens"], 1024)
        self.assertIn("technical reliability", result["comparison_type"])

    def test_flat_v22_retry_count_is_not_lost(self) -> None:
        result = compare_v21_v22(
            {"retry_protocol": {"retry_trigger_count": 2}},
            {"retry_trigger_count": 0},
        )
        self.assertEqual(result["v2_1"]["retry_trigger_count"], 2)
        self.assertEqual(result["v2_2"]["retry_trigger_count"], 0)


if __name__ == "__main__":
    unittest.main()
