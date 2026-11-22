from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import previous_failure_recovery


class PreviousFailureRecoveryTests(unittest.TestCase):
    def test_recovered_failure_is_marked_output_budget_recovery(self) -> None:
        old = [{"question_id": "q1", "attempt_number": 1, "finish_reason": "length", "completion_tokens": 768,
                "schema_status": False, "result": {"status": "generation_error"}}]
        new = [{"question_id": "q1", "attempt_number": 1, "finish_reason": "stop", "completion_tokens": 910,
                "schema_status": True, "result": {"status": "answered"}}]
        report = previous_failure_recovery(question_id="q1", v21_attempts=old, v22_attempts=new)
        self.assertTrue(report["output_budget_recovery"])


if __name__ == "__main__":
    unittest.main()
