import unittest

from src.evaluation.generation.protocol_v2 import validate_v2_output


class GenerationV2SchemaTests(unittest.TestCase):
    def test_answered_requires_nonempty_answer_and_context_citation(self):
        self.assertEqual(validate_v2_output({
            "question_id": "q1", "status": "answered", "answer": "有證據", "citations": ["C1"],
        }, "q1"), [])
        self.assertIn("answered_without_citations", validate_v2_output({
            "question_id": "q1", "status": "answered", "answer": "有證據", "citations": [],
        }, "q1"))
        self.assertIn("citation_not_context_id", validate_v2_output({
            "question_id": "q1", "status": "answered", "answer": "有證據", "citations": ["chunk-id"],
        }, "q1"))

    def test_insufficient_evidence_can_have_empty_citations_but_error_is_not_model_status(self):
        self.assertEqual(validate_v2_output({
            "question_id": "q1", "status": "insufficient_evidence", "answer": "資料不足", "citations": [],
        }, "q1"), [])
        self.assertIn("invalid_status", validate_v2_output({
            "question_id": "q1", "status": "generation_error", "answer": "", "citations": [],
        }, "q1"))


if __name__ == "__main__":
    unittest.main()
