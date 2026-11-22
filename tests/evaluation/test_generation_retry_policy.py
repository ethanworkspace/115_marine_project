from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import MAX_ATTEMPTS, should_retry


class GenerationRetryPolicyTests(unittest.TestCase):
    def test_retry_policy_allows_one_retry_for_invalid_result(self) -> None:
        self.assertTrue(should_retry({"json_parse_valid": False, "schema_valid": False}, attempt_number=1))

    def test_success_does_not_retry(self) -> None:
        result = {"json_parse_valid": True, "schema_valid": True, "status_valid": True}
        self.assertFalse(should_retry(result, attempt_number=1))

    def test_maximum_attempts_is_two(self) -> None:
        self.assertEqual(MAX_ATTEMPTS, 2)
        self.assertFalse(should_retry({"json_parse_valid": False}, attempt_number=2))


if __name__ == "__main__":
    unittest.main()
