from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import retry_impact


class RetrySuccessTests(unittest.TestCase):
    def test_valid_second_attempt_is_technical_retry_recovery(self) -> None:
        first = {"question_id": "q1", "attempt_number": 1, "attempt_valid": False,
                 "result": {"status": "generation_error", "answer": "", "citations": []}}
        second = {"question_id": "q1", "attempt_number": 2, "attempt_valid": True,
                  "result": {"status": "answered", "answer": "回答", "citations": ["C1"]}}
        impact = retry_impact(first, second)
        self.assertTrue(impact["technical_retry_recovery"])
        self.assertFalse(impact["final_attempt_failed"])
        self.assertTrue(impact["status_changed"])


if __name__ == "__main__":
    unittest.main()
