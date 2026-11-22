import unittest

from src.evaluation.grounded.pipeline import validate_grounded_question
from tests.evaluation.grounded_fixtures import make_corpus_record, make_evidence, make_question


class EvidenceBindingTests(unittest.TestCase):
    def test_question_resolves_to_retrieval_chunk_page_and_document(self):
        corpus = make_corpus_record()
        question = make_question([make_evidence(corpus)])
        self.assertEqual(validate_grounded_question(question, {corpus["chunk_id"]: corpus}), [])

    def test_context_only_chunk_cannot_be_required(self):
        corpus = make_corpus_record()
        question = make_question([make_evidence(corpus)])
        corpus["retrieval_role"] = "context_only"
        self.assertIn("required_chunk_not_retrieval",
                      validate_grounded_question(question, {corpus["chunk_id"]: corpus}))

    def test_excluded_duplicate_cannot_be_required(self):
        corpus = make_corpus_record()
        corpus["duplicate_status"] = "exact_duplicate"
        question = make_question([make_evidence(make_corpus_record())])
        self.assertIn("required_chunk_noncanonical_duplicate",
                      validate_grounded_question(question, {corpus["chunk_id"]: corpus}))


if __name__ == "__main__":
    unittest.main()

