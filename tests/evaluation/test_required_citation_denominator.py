import unittest

from src.evaluation.generation.protocol_v2 import required_citation_recall
from src.evaluation.generation.runner_v2 import _summary


class RequiredCitationDenominatorTests(unittest.TestCase):
    def test_metrics_separate_all_present_and_answered_denominators(self):
        contexts = [{"context_id": "C1", "chunk_id": "required", "document_id": "d", "page": 1}]
        citations = [{"strict_valid": True, "recoverable_valid": True, "chunk_id": "required"}]
        answered = required_citation_recall(required_chunk_ids=["required"], contexts=contexts,
                                            citations=citations, status="answered")
        abstained = required_citation_recall(required_chunk_ids=["required"], contexts=contexts,
                                             citations=[], status="insufficient_evidence")
        self.assertEqual(answered["required_chunk_count_all_questions"], 1)
        self.assertEqual(answered["required_chunk_count_present"], 1)
        self.assertEqual(answered["required_chunk_count_present_and_answered"], 1)
        self.assertEqual(abstained["required_chunk_count_present_and_answered"], 0)
        self.assertTrue(answered["question_strict_all_available_required_cited"])

    def test_aggregate_question_level_all_required_recall_uses_real_key(self):
        contexts = [{"context_id": "C1", "chunk_id": "required", "document_id": "d", "page": 1}]
        citations = [{"strict_valid": True, "recoverable_valid": True, "chunk_id": "required"}]
        metric = required_citation_recall(required_chunk_ids=["required"], contexts=contexts,
                                          citations=citations, status="answered")
        metric.update({
            "strict_cited_required_chunk_count_present": 1,
            "recoverable_cited_required_chunk_count_present": 1,
            "strict_cited_required_chunk_count_present_and_answered": 1,
            "recoverable_cited_required_chunk_count_present_and_answered": 1,
        })
        row = {
            "status": "answered", "required_evidence_in_context": True,
            "required_evidence_citation": metric, "citation_count": 1,
            "strict_citation_count": 1, "recoverable_citation_count": 1,
            "citation_error_taxonomy": {}, "schema_valid": True,
            "json_parse_valid": True, "status_valid": True,
            "citation_parse_valid": True, "silver_reference_similarity": None,
            "calculation_numeric_evaluation": None,
        }
        result = _summary([row], [{"raw_output": "{}"}])
        self.assertEqual(
            result["required_evidence_question_recall"]["strict_all_required_cited_when_present_and_answered"], 1.0
        )


if __name__ == "__main__":
    unittest.main()
