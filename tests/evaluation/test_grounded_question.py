import unittest

from tests.evaluation.grounded_fixtures import make_evidence, make_question


class GroundedQuestionTests(unittest.TestCase):
    def test_record_has_corpus_binding_fields_and_silver_label(self):
        question = make_question([make_evidence()])
        for key in ("question_id", "question", "reference_answer", "required_chunks", "required_pages",
                    "required_documents", "evidence_snapshot", "evaluation_corpus_sha256"):
            self.assertIn(key, question)
        self.assertEqual(question["benchmark_type"], "silver")
        self.assertEqual(question["generation_source"], "corpus_grounded_ai")
        self.assertEqual(question["mapping_status"], "exact_by_construction")


if __name__ == "__main__":
    unittest.main()
