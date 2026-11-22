import unittest

from src.evaluation.gold import validate_gold_record


def base_record():
    return {
        "question_id": "q1", "question": None, "species": None, "category": "fact", "difficulty": None,
        "answerable": None, "expected_abstention": None, "gold_answer": None, "gold_documents": [],
        "gold_pages": [], "gold_chunks": [], "required_chunks": [], "acceptable_chunks": [],
        "supporting_claims": [], "conflicting_chunks": [], "source_verification_required": False,
        "source_verification_status": "pending", "annotation_status": "draft", "annotator": None,
        "reviewer": None, "notes": None,
    }


class GoldReferenceTests(unittest.TestCase):
    def test_unknown_chunk_reference_fails(self):
        record = base_record()
        record["gold_chunks"] = ["missing"]
        self.assertTrue(any("missing corpus chunk" in error for error in validate_gold_record(record, {})))

    def test_required_evidence_must_be_retrieval_or_explicitly_acceptable(self):
        record = base_record()
        record["required_chunks"] = ["parent"]
        corpus = {"parent": {"retrieval_role": "context_only"}}
        self.assertTrue(any("not retrieval evidence" in error for error in validate_gold_record(record, corpus)))
        record["acceptable_chunks"] = ["parent"]
        self.assertFalse(any("not retrieval evidence" in error for error in validate_gold_record(record, corpus)))

    def test_locked_record_requires_gold_evidence(self):
        record = base_record()
        record.update(annotation_status="locked", question="Q", gold_answer="A")
        errors = validate_gold_record(record, {})
        self.assertTrue(any("locked records require gold" in error for error in errors))

    def test_blocked_high_risk_may_have_no_answer(self):
        record = base_record()
        record.update(annotation_status="blocked", risk_level="high", category="drug")
        self.assertEqual(validate_gold_record(record, {}), [])


if __name__ == "__main__":
    unittest.main()
