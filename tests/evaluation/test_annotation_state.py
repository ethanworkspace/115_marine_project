import unittest

from src.evaluation.annotation import validate_annotation_transition


class AnnotationStateTests(unittest.TestCase):
    def test_annotated_requires_human_question_decisions_category_and_difficulty(self):
        errors = validate_annotation_transition({"annotation_status": "draft"}, "annotated", annotator="A", reviewer=None, question_verified=False, evidence_verified=False)
        self.assertTrue(any("human-written question" in error for error in errors))
        self.assertTrue(any("answerability decision" in error for error in errors))
        self.assertTrue(any("abstention decision" in error for error in errors))
        self.assertTrue(any("confirmed category" in error for error in errors))
        self.assertTrue(any("difficulty decision" in error for error in errors))

    def test_answerable_requires_gold_answer_and_evidence(self):
        row = {"question": "Q", "answerable": True, "expected_abstention": False, "category_verified": True, "difficulty": "easy"}
        errors = validate_annotation_transition(row, "annotated", annotator="A", reviewer=None, question_verified=False, evidence_verified=False)
        self.assertTrue(any("gold_answer" in error for error in errors))
        self.assertTrue(any("manually selected evidence" in error for error in errors))

    def test_reviewed_requires_different_reviewer_and_confirmation(self):
        row = {"annotation_status": "annotated"}
        checks = {key: True for key in ("question_supported", "gold_answer_supported", "required_chunks_reasonable", "acceptable_chunks_reasonable", "species_within_evidence", "category_reasonable", "difficulty_reasonable")}
        self.assertEqual(validate_annotation_transition(row, "reviewed", annotator="Alice", reviewer="Bob", question_verified=True, evidence_verified=True, reviewer_confirmations=checks, review_notes="Checked source evidence."), [])
        errors = validate_annotation_transition(row, "reviewed", annotator="Alice", reviewer="Alice", question_verified=True, evidence_verified=False, reviewer_confirmations={}, review_notes=None)
        self.assertTrue(any("different reviewer" in error for error in errors))
        self.assertTrue(any("evidence_verified" in error for error in errors))
        self.assertTrue(any("review_notes" in error for error in errors))
        self.assertTrue(any("reviewer confirmation" in error for error in errors))

    def test_development_workbench_cannot_lock(self):
        errors = validate_annotation_transition({}, "locked", annotator="A", reviewer="B", question_verified=True, evidence_verified=True)
        self.assertTrue(any("cannot set locked" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
