from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v2 import sha256_text
from src.evaluation.generation.retry_v21 import build_attempt_record


class AttemptPreservationTests(unittest.TestCase):
    def test_raw_output_and_hash_are_preserved(self) -> None:
        output = '{"status":"answered"}'
        attempt = build_attempt_record(question_id="q1", attempt_number=1,
            result={"json_parse_valid": True, "schema_valid": True, "status_valid": True},
            raw={"raw_output": output, "raw_output_sha256": sha256_text(output)})
        self.assertEqual(attempt["raw_output"], output)
        self.assertEqual(attempt["raw_output_sha256"], sha256_text(output))
        self.assertTrue(attempt["raw_output_preserved"])

    def test_empty_stream_is_still_recorded_and_hashed(self) -> None:
        attempt = build_attempt_record(question_id="q1", attempt_number=1,
            result={"json_parse_valid": False, "schema_valid": False}, raw={"raw_output": ""})
        self.assertEqual(attempt["raw_output_sha256"], sha256_text(""))
        self.assertTrue(attempt["raw_output_preserved"])


if __name__ == "__main__":
    unittest.main()
