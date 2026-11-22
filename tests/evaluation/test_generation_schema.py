import unittest

from src.evaluation.generation.evaluation import validate_model_output


class GenerationSchemaTests(unittest.TestCase):
    def test_valid_answer(self):
        citation = {"context_id": "C1", "chunk_id": "c1", "document_id": "d1", "page": 1}
        self.assertEqual(validate_model_output({"question_id": "q1", "status": "answered", "answer": "a", "citations": [citation]}, "q1"), (True, []))

    def test_invalid_or_wrong_question(self):
        valid, errors = validate_model_output({"question_id": "q2", "status": "answered", "answer": "a", "citations": [], "confidence": 0.9}, "q1")
        self.assertFalse(valid)
        self.assertIn("schema_fields_mismatch", errors)
        self.assertIn("question_id_mismatch", errors)


if __name__ == "__main__":
    unittest.main()
