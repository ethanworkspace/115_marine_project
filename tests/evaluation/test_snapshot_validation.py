import unittest

from src.evaluation.grounded.pipeline import validate_grounded_question
from tests.evaluation.grounded_fixtures import make_corpus_record, make_evidence, make_question


class SnapshotValidationTests(unittest.TestCase):
    def test_snapshot_checksum_and_text_are_verified(self):
        corpus = make_corpus_record()
        question = make_question([make_evidence(corpus)])
        question["evidence_snapshot"][0]["text_snapshot"] += "被竄改"
        errors = validate_grounded_question(question, {corpus["chunk_id"]: corpus})
        self.assertIn("snapshot_checksum_mismatch", errors)
        self.assertIn("snapshot_text_mismatch", errors)

    def test_wrong_document_and_page_fail_explicitly(self):
        corpus = make_corpus_record()
        question = make_question([make_evidence(corpus)])
        question["required_pages"] = [{"document_id": corpus["document_id"], "page": 99}]
        self.assertIn("required_page_mismatch",
                      validate_grounded_question(question, {corpus["chunk_id"]: corpus}))


if __name__ == "__main__":
    unittest.main()

