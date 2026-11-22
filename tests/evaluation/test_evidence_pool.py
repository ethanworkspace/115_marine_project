import unittest

from src.evaluation.grounded.pipeline import build_evidence_pool
from tests.evaluation.grounded_fixtures import make_corpus_record


class EvidencePoolTests(unittest.TestCase):
    def test_pool_filters_roles_risk_and_noncanonical_duplicates(self):
        good = make_corpus_record("good")
        context = make_corpus_record("context")
        context["retrieval_role"] = "context_only"
        high = make_corpus_record("high")
        high["risk_level"] = "high"
        duplicate = make_corpus_record("duplicate")
        duplicate["duplicate_status"] = "exact_duplicate"
        pool = build_evidence_pool([good, context, high, duplicate])
        self.assertEqual([row["chunk_id"] for row in pool], ["good"])
        self.assertEqual(pool[0]["evidence_quality_status"], "accepted")

    def test_short_content_is_not_accepted(self):
        row = make_corpus_record("short", text="吳郭魚資料")
        pool = build_evidence_pool([row])
        self.assertEqual(pool[0]["evidence_quality_status"], "rejected")


if __name__ == "__main__":
    unittest.main()

