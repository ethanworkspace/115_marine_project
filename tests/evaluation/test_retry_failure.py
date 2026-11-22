from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import retry_impact


class RetryFailureTests(unittest.TestCase):
    def test_second_failure_is_final_generation_error(self) -> None:
        first = {"question_id": "q1", "attempt_number": 1, "attempt_valid": False,
                 "result": {"status": "generation_error", "json_parse_valid": False}}
        second = {"question_id": "q1", "attempt_number": 2, "attempt_valid": False,
                  "result": {"status": "generation_error", "json_parse_valid": False}}
        impact = retry_impact(first, second)
        self.assertTrue(impact["final_attempt_failed"])
        self.assertFalse(impact["technical_retry_recovery"])
        self.assertIsNone(impact["answer_similarity"])
        self.assertIsNone(impact["citation_set_jaccard"])


if __name__ == "__main__":
    unittest.main()
