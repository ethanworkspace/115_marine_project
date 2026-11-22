from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import MAX_ATTEMPTS, validate_attempt_records


class RetryMaxAttemptsTests(unittest.TestCase):
    def test_two_attempts_are_the_limit(self) -> None:
        self.assertEqual(MAX_ATTEMPTS, 2)
        valid = {"attempt_valid": False, "result": {"json_parse_valid": False}}
        validate_attempt_records([
            {"question_id": "q1", "attempt_number": 1, **valid},
            {"question_id": "q1", "attempt_number": 2, **valid},
        ], question_ids=["q1"])

    def test_third_attempt_is_rejected(self) -> None:
        rows = [{"question_id": "q1", "attempt_number": n, "attempt_valid": False,
                 "result": {"json_parse_valid": False}} for n in (1, 2, 3)]
        with self.assertRaises(ValueError):
            validate_attempt_records(rows, question_ids=["q1"])


if __name__ == "__main__":
    unittest.main()
