from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import should_retry


class RetryOnlyOnFailureTests(unittest.TestCase):
    def test_valid_first_attempt_is_accepted(self) -> None:
        valid = {"json_parse_valid": True, "schema_valid": True, "status_valid": True}
        self.assertFalse(should_retry(valid, attempt_number=1))

    def test_execution_failure_retries_even_if_result_fields_look_valid(self) -> None:
        failed = {"json_parse_valid": True, "schema_valid": True, "status_valid": True, "execution_error": "connection reset"}
        self.assertTrue(should_retry(failed, attempt_number=1))


if __name__ == "__main__":
    unittest.main()
