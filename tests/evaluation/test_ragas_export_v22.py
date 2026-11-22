from __future__ import annotations

import unittest

from src.evaluation.generation.protocol_v22 import build_ragas_row_v22


class RagasExportV22Tests(unittest.TestCase):
    def test_export_fails_until_ready(self) -> None:
        with self.assertRaises(ValueError):
            build_ragas_row_v22(question={"question_id": "q", "question": "Q"}, answer="A", contexts=[],
                                condition="G0", model="gemma2:9b", attempts=1, ready=False)

    def test_export_has_condition_and_silver_protocol_labels(self) -> None:
        row = build_ragas_row_v22(question={"question_id": "q", "question": "Q", "reference_answer": "R"},
            answer="A", contexts=[{"text": "Evidence"}], condition="G1", model="gemma2:9b", attempts=2, ready=True)
        self.assertEqual(row["condition"], "e4_top5")
        self.assertEqual(row["benchmark_type"], "silver")
        self.assertEqual(row["generation_protocol"], "v2.2")


if __name__ == "__main__":
    unittest.main()
