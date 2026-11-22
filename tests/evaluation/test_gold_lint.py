import unittest

from src.evaluation.annotation import sha256_text
from src.evaluation.gold_lint import lint_question
from tests.evaluation.helpers import make_chunk, make_doc, build


def record(**updates):
    value = {
        "question_id": "dev-q", "split": "development", "category": "fact", "risk_level": "normal",
        "answerable": None, "expected_abstention": None, "gold_chunks": [], "required_chunks": [],
        "acceptable_chunks": [], "conflicting_chunks": [], "gold_evidence_snapshot": [],
        "annotation_status": "draft", "evidence_verified": False, "question_verified": False,
        "source_verification_status": "pending", "evaluation_corpus_version": "evaluation-corpus-v1",
        "evaluation_corpus_sha256": "a" * 64,
    }
    value.update(updates)
    return value


class GoldLintTests(unittest.TestCase):
    def setUp(self):
        self.corpus = build([make_chunk("retrieval"), make_chunk("duplicate", checksum="xyz")], [make_doc()])
        self.by_id = {row["chunk_id"]: row for row in self.corpus}

    def lint(self, row):
        return lint_question(row, self.by_id, current_corpus_version="evaluation-corpus-v1", current_corpus_sha256="a" * 64)

    def test_answerable_requires_gold_evidence(self):
        self.assertIn("answerable_without_evidence", {issue["code"] for issue in self.lint(record(answerable=True, expected_abstention=False))})

    def test_missing_required_chunk_is_reported(self):
        self.assertIn("missing_chunk", {issue["code"] for issue in self.lint(record(required_chunks=["absent"]))})

    def test_answerability_and_abstention_conflict(self):
        self.assertIn("answerability_abstention_conflict", {issue["code"] for issue in self.lint(record(answerable=True, expected_abstention=True))})

    def test_duplicate_noncanonical_chunk_cannot_be_gold(self):
        duplicate = next(row for row in self.corpus if row["chunk_id"] == "duplicate")
        duplicate["duplicate_status"] = "exact_duplicate"
        duplicate["retrieval_role"] = "excluded"
        errors = self.lint(record(required_chunks=["duplicate"]))
        self.assertIn("noncanonical_duplicate", {issue["code"] for issue in errors})
        self.assertIn("excluded_chunk", {issue["code"] for issue in errors})

    def test_reviewed_requires_evidence_verification(self):
        codes = {issue["code"] for issue in self.lint(record(annotation_status="reviewed", evidence_verified=False))}
        self.assertIn("review_without_evidence_verification", codes)

    def test_reviewed_requires_independent_review_confirmations_and_notes(self):
        row = record(annotation_status="reviewed", annotator="Alice", reviewer="Bob", evidence_verified=True, question_verified=True)
        codes = {issue["code"] for issue in self.lint(row)}
        self.assertIn("missing_reviewer_confirmation", codes)
        self.assertIn("missing_review_provenance", codes)

    def test_unverified_high_risk_cannot_be_development_gold(self):
        codes = {issue["code"] for issue in self.lint(record(category="drug", risk_level="high", annotation_status="locked"))}
        self.assertIn("unverified_high_risk_locked", codes)
        self.assertIn("high_risk_in_development", codes)

    def test_snapshot_source_checksum_mismatch_is_reported(self):
        text = "snapshot text"
        snapshot = {"chunk_id": "retrieval", "document_id": "doc-a", "page": 1,
                    "content_checksum": "wrong", "text_snapshot": text, "snapshot_sha256": sha256_text(text)}
        codes = {issue["code"] for issue in self.lint(record(gold_evidence_snapshot=[snapshot]))}
        self.assertIn("snapshot_source_checksum_mismatch", codes)


if __name__ == "__main__":
    unittest.main()
