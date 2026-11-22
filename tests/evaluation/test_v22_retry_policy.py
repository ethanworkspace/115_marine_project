from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.evaluation.generation.protocol_v22 import MAX_ATTEMPTS, MAX_OUTPUT_TOKENS
from src.evaluation.generation.retry_v21 import should_retry
from src.evaluation.generation import runner_v22


class V22RetryPolicyTests(unittest.TestCase):
    def test_same_two_attempt_cap_is_used_with_1024_budget(self) -> None:
        self.assertEqual(MAX_ATTEMPTS, 2)
        self.assertEqual(MAX_OUTPUT_TOKENS, 1024)
        invalid = {"json_parse_valid": False, "schema_valid": False}
        self.assertTrue(should_retry(invalid, attempt_number=1))
        self.assertFalse(should_retry(invalid, attempt_number=2))

    def _execute_synthetic_condition(self, *, first_valid: bool, second_valid: bool = True) -> dict:
        """Exercise the actual condition dispatch, not just the retry helper."""
        question = {"question_id": "q1", "question": "A test question", "reference_answer": "test answer",
                    "required_chunks": ["c1"], "category": "fact"}
        context = {"context_id": "C1", "chunk_id": "c1", "document_id": "d1", "page": 1,
                   "text": "test evidence"}
        frozen = {"questions": [question], "hashes": {}, "corpus_by_id": {"c1": context}}
        real_run_question = runner_v22._run_question
        calls = []

        def synthetic_run(**kwargs):
            attempt_number = kwargs["attempt_number"]
            calls.append(attempt_number)
            valid = first_valid if attempt_number == 1 else second_valid
            parsed = {"question_id": "q1", "status": "answered", "answer": "test answer", "citations": ["C1"]}
            raw = json.dumps(parsed) if valid else '{"status":'
            response = {"parsed": parsed if valid else None, "raw_output": raw,
                        "raw_output_sha256": runner_v22.sha256_text(raw),
                        "parse_error": None if valid else "JSONDecodeError: truncated JSON",
                        "execution_error": None, "latency_seconds": .1, "ttft_seconds": .01,
                        "prompt_tokens": 10, "completion_tokens": 20 if valid else 1024,
                        "tokens_per_second": 100, "load_duration_ns": 0,
                        "done_reason": "stop" if valid else "length"}
            return real_run_question(**kwargs, call_fn=lambda **_: response)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schemas").mkdir()
            (root / "schemas/generation_output_v2.schema.json").write_text("{}", encoding="utf-8")
            with patch.object(runner_v22, "QUESTION_COUNT", 1), \
                 patch.object(runner_v22, "_run_question", side_effect=synthetic_run), \
                 patch.object(runner_v22, "_repeatability", return_value={}), \
                 patch.object(runner_v22, "_git_commit", return_value=None):
                result = runner_v22._run_condition(root, condition="G0", frozen=frozen,
                    model_info={"default_model": "gemma2:9b", "ollama_endpoint": "http://127.0.0.1:11434"},
                    prompt="fixed test prompt", contexts={"q1": [context]}, baseline_tokens={"q1": 10})
                return {"calls": calls, "summary": result["summary"], "attempts": result["attempts"]}

    def test_valid_first_pass_dispatches_exactly_once(self) -> None:
        result = self._execute_synthetic_condition(first_valid=True)
        self.assertEqual(result["calls"], [1])
        self.assertEqual(result["summary"]["retry_trigger_count"], 0)

    def test_invalid_first_pass_dispatches_one_fresh_retry(self) -> None:
        result = self._execute_synthetic_condition(first_valid=False, second_valid=True)
        self.assertEqual(result["calls"], [1, 2])
        self.assertEqual(result["summary"]["retry_success_count"], 1)
        self.assertEqual(result["summary"]["final_schema_valid_rate"], 1)

    def test_two_failures_stop_without_a_third_attempt(self) -> None:
        result = self._execute_synthetic_condition(first_valid=False, second_valid=False)
        self.assertEqual(result["calls"], [1, 2])
        self.assertEqual(result["summary"]["retry_failure_count"], 1)
        self.assertEqual(result["summary"]["generation_error_count"], 1)


if __name__ == "__main__":
    unittest.main()
