from __future__ import annotations

import unittest

from src.evaluation.generation.retry_v21 import build_ragas_export_row


class RagasExportV21Tests(unittest.TestCase):
    def test_export_is_blocked_when_not_ready(self) -> None:
        with self.assertRaises(ValueError):
            build_ragas_export_row(question={"question_id": "q1", "question": "Q"}, answer="A",
                                   contexts=[], attempts=1, final_output_source="attempt_1", ready=False)

    def test_export_has_silver_and_protocol_labels(self) -> None:
        row = build_ragas_export_row(question={"question_id": "q1", "question": "Q", "reference_answer": "R"},
            answer="A", contexts=[{"text": "Context"}], attempts=2,
            final_output_source="attempt_2", ready=True)
        self.assertEqual(row["benchmark_type"], "silver")
        self.assertEqual(row["generation_protocol"], "v2.1")
        self.assertEqual(row["generation_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
