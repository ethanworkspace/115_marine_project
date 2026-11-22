import unittest

from src.evaluation.source_mapping import validate_silver_v2_question


class SilverV2Tests(unittest.TestCase):
    def setUp(self):
        self.corpus = {"c1": {
            "chunk_id": "c1", "canonical_chunk_id": "c1", "document_id": "d1", "canonical_document_id": "d1",
            "retrieval_role": "retrieval", "duplicate_status": "none", "ingestion_status": "accepted",
        }}
        self.question = {
            "question_id": "q1", "original_question": "Q?", "original_reference_answer": "A",
            "expected_sources": [], "expected_facts": [], "mapped_documents": ["d1"], "mapped_pages": [],
            "mapped_chunks": [{"chunk_id": "c1", "document_id": "d1"}],
            "evidence_mapping_status": "high_confidence", "mapping_method": "exact_normalized_text", "mapping_score": 1.0,
        }

    def test_v2_preserves_question_and_reference_and_validates_chunk(self):
        validate_silver_v2_question(self.question, self.corpus)
        self.assertEqual(self.question["original_question"], "Q?")
        self.assertEqual(self.question["original_reference_answer"], "A")

    def test_duplicate_or_excluded_chunk_cannot_be_expected_evidence(self):
        bad = {**self.corpus["c1"], "retrieval_role": "context_only"}
        with self.assertRaises(ValueError):
            validate_silver_v2_question(self.question, {"c1": bad})


if __name__ == "__main__":
    unittest.main()
