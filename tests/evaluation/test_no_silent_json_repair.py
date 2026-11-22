from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import classify_failure


class NoSilentJsonRepairTests(unittest.TestCase):
    def test_invalid_json_remains_a_parse_failure(self) -> None:
        failure = classify_failure(raw_output='{"answer":"unfinished', parse_error="Unterminated string",
                                   schema_error=["json_parse_failure"], execution_error=None,
                                   finish_reason="length")
        self.assertEqual(failure, "truncated_json")

    def test_no_recovery_path_changes_first_pass_validity(self) -> None:
        self.assertEqual(classify_failure(raw_output="not json", parse_error="JSONDecodeError",
                                          schema_error=None, execution_error=None,
                                          finish_reason="stop"), "malformed_json")


if __name__ == "__main__":
    unittest.main()
