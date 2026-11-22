import unittest

from src.evaluation.corpus_gaps import silver_v3_has_material_improvement
from src.evaluation.phase10_recovery import validate_v3_questions


class SilverV3MappingTests(unittest.TestCase):
    def test_identical_mapping_does_not_justify_v3_copy(self):
        rows = [{"question_id": "q1", "evidence_mapping_status": "medium_confidence", "mapped_chunks": [{"chunk_id": "c1"}]}]
        self.assertFalse(silver_v3_has_material_improvement(rows, rows))

    def test_material_mapping_change_is_detected(self):
        before = [{"question_id": "q1", "evidence_mapping_status": "unmapped", "mapped_chunks": []}]
        after = [{"question_id": "q1", "evidence_mapping_status": "high_confidence", "mapped_chunks": [{"chunk_id": "c1"}]}]
        self.assertTrue(silver_v3_has_material_improvement(before, after))

    def test_v3_mapping_must_resolve_to_canonical_retrieval_chunk(self):
        question = {"benchmark_type": "silver", "generation_source": "ai_question_bank",
                    "mapped_chunks": [{"chunk_id": "c", "document_id": "d"}]}
        corpus = [{"chunk_id": "c", "document_id": "d", "retrieval_role": "retrieval",
                   "duplicate_status": "canonical"}]
        validate_v3_questions([question], corpus)

    def test_context_only_chunk_cannot_be_expected_retrieval_evidence(self):
        question = {"benchmark_type": "silver", "generation_source": "ai_question_bank",
                    "mapped_chunks": [{"chunk_id": "p", "document_id": "d"}]}
        corpus = [{"chunk_id": "p", "document_id": "d", "retrieval_role": "context_only",
                   "duplicate_status": "canonical"}]
        with self.assertRaises(ValueError):
            validate_v3_questions([question], corpus)


if __name__ == "__main__":
    unittest.main()
