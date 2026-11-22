import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.generation.runner import _write_ragas_export


class RagasExportTests(unittest.TestCase):
    def test_export_labels_reference_as_silver(self):
        question = {
            "question_id": "q", "question": "問", "reference_answer": "參考答案",
            "required_chunks": ["c"], "evidence_snapshot": [{"chunk_id": "c", "document_id": "d", "page": 1,
                "content_checksum": "2b1b6a8dc26d33894ddcf3c722d7f159d3f2e31f7d398f302931f184ce8e8d3d", "text_snapshot": "evidence"}],
        }
        import hashlib
        question["evidence_snapshot"][0]["content_checksum"] = hashlib.sha256(b"evidence").hexdigest()
        corpus = {"c": {"chunk_id": "c", "document_id": "d", "page_start": 1, "page_end": 1, "text": "evidence",
                        "content_checksum": question["evidence_snapshot"][0]["content_checksum"]}}
        frozen = {"questions": [question], "corpus_by_id": corpus, "e4_trace_by_question": {"q": [
            {"rank": i, "chunk_id": f"c{i}", "document_id": "d", "page": 1} for i in range(1, 6)
        ]}}
        corpus.update({f"c{i}": {"chunk_id": f"c{i}", "document_id": "d", "page_start": 1, "page_end": 1,
                                "text": f"evidence{i}", "retrieval_role": "retrieval", "duplicate_status": "none"}
                       for i in range(1, 6)})
        with tempfile.TemporaryDirectory() as tmp:
            _write_ragas_export(Path(tmp), frozen, [{"question_id": "q", "answer": "a", "status": "answered"}])
            row = json.loads((Path(tmp) / "data/evaluation/generation/ragas_input_v1.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(row["silver_reference"])
        self.assertEqual(row["reference_answer"], "參考答案")


if __name__ == "__main__":
    unittest.main()
