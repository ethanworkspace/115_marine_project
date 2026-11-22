from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import first_pass_metrics


class FirstPassVsFinalMetricsTests(unittest.TestCase):
    def test_first_pass_rates_use_attempt_one_only(self) -> None:
        attempts = [
            {"question_id": "q1", "attempt_number": 1, "json_parse_status": False,
             "schema_status": False, "citation_parse_status": False, "attempt_valid": False},
            {"question_id": "q1", "attempt_number": 2, "json_parse_status": True,
             "schema_status": True, "citation_parse_status": True, "attempt_valid": True},
            {"question_id": "q2", "attempt_number": 1, "json_parse_status": True,
             "schema_status": True, "citation_parse_status": True, "attempt_valid": True},
        ]
        metrics = first_pass_metrics(attempts, question_count=2)
        self.assertEqual(metrics["first_pass_schema_valid_count"], 1)
        self.assertEqual(metrics["first_pass_schema_valid_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
