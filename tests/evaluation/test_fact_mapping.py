import unittest

from src.evaluation.source_mapping import _unmapped_reason, map_fact


class FactMappingTests(unittest.TestCase):
    def setUp(self):
        self.text = "吳郭魚最適生長水溫約25至30°C。"
        self.row = {
            "chunk_id": "c1", "canonical_chunk_id": "c1", "document_id": "d1", "canonical_document_id": "d1",
            "retrieval_role": "retrieval", "duplicate_status": "none", "ingestion_status": "accepted",
            "page_start": 3, "page_end": 3, "text": self.text,
        }
        self.fact = {"事實ID": "F1", "可核對事實（已改寫）": self.text, "來源ID": "S01"}
        self.aliases = {"fish.xlsx::S01": {"document_id": "d1", "mapping_confidence": "exact", "source_verified": False}}

    def test_fact_mapping_is_deterministic_and_resolves_page_chunk(self):
        first = map_fact(self.fact, "fish.xlsx", {"S01": {}}, self.aliases, [self.row])
        second = map_fact(self.fact, "fish.xlsx", {"S01": {}}, self.aliases, [self.row])
        self.assertEqual(first, second)
        self.assertEqual(first["mapping_status"], "exact")
        self.assertEqual(first["mapped_documents"], ["d1"])
        self.assertEqual(first["mapped_pages"][0]["page"], 3)
        self.assertEqual(first["mapped_chunks"][0]["chunk_id"], "c1")
        self.assertIs(first["source_verified"], False)

    def test_context_only_parent_never_becomes_expected_chunk(self):
        parent = {**self.row, "chunk_id": "parent", "canonical_chunk_id": "parent", "retrieval_role": "context_only", "chunk_type": "parent"}
        result = map_fact(self.fact, "fish.xlsx", {"S01": {}}, self.aliases, [parent])
        self.assertEqual(result["mapped_chunks"], [])
        self.assertEqual(result["mapping_status"], "unmapped")

    def test_review_page_candidate_is_reported_but_not_mapped(self):
        review = {
            **self.row, "chunk_id": "review", "canonical_chunk_id": "review",
            "document_id": "d1", "canonical_document_id": "d1", "retrieval_role": "excluded",
            "ingestion_status": "review", "exclusion_reason": "page_not_chunked_due_to_ingestion_gate",
        }
        result = map_fact(self.fact, "fish.xlsx", {"S01": {}}, self.aliases, [], [review])
        self.assertEqual(result["mapped_chunks"], [])
        self.assertTrue(result["review_page_excluded_candidate"])
        reason = _unmapped_reason({"expected_sources": [{"source_id": "S01"}], "expected_facts": []}, [result], [{"mapping_confidence": "high"}])
        self.assertEqual(reason, "review_page_excluded")

    def test_one_verified_source_does_not_verify_multiple_source_fact(self):
        fact = {"事實ID": "F1", "可核對事實（已改寫）": self.text, "來源ID": "S01;S02"}
        aliases = {
            "fish.xlsx::S01": {"document_id": "d1", "mapping_confidence": "high", "source_verified": True, "excel_source_id": "S01"},
            "fish.xlsx::S02": {"document_id": "d1", "mapping_confidence": "high", "source_verified": False, "excel_source_id": "S02"},
        }
        result = map_fact(fact, "fish.xlsx", {"S01": {}, "S02": {}}, aliases, [self.row])
        self.assertIs(result["source_verified"], False)
        self.assertEqual(result["source_verification_by_source"], {"S01": True, "S02": False})

    def test_unusable_ocr_is_reported_as_mapping_gap_only(self):
        aliases = {"fish.xlsx::S01": {"document_id": "d1", "mapping_confidence": "high", "source_verified": False, "excel_source_id": "S01"}}
        ocr = [{"document_id": "d1", "page_number": 9, "ocr_text": "", "ocr_quality_status": "backend_unavailable"}]
        result = map_fact(self.fact, "fish.xlsx", {"S01": {}}, aliases, [], [], ocr)
        self.assertEqual(result["mapped_chunks"], [])
        self.assertTrue(result["ocr_missing_candidate"])


if __name__ == "__main__":
    unittest.main()
