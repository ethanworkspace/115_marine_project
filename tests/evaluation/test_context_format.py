import unittest

from src.evaluation.generation.contexts import make_user_prompt


class ContextFormatTests(unittest.TestCase):
    def test_only_context_provenance_and_text_are_formatted(self):
        prompt = make_user_prompt("q1", "question", [{"context_id": "C1", "chunk_id": "secret", "document_id": "doc", "page": 4, "text": "evidence", "rank": 1}])
        self.assertIn("[C1]", prompt)
        self.assertIn("document_id: doc", prompt)
        self.assertIn("page: 4", prompt)
        self.assertIn("evidence", prompt)
        self.assertIn("chunk_id: secret", prompt)
        self.assertNotIn("rank", prompt)
        self.assertIn("question_id：q1", prompt)


if __name__ == "__main__":
    unittest.main()
