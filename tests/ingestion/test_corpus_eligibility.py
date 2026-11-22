import unittest

from src.ingestion.gate import aggregate_document


class CorpusEligibilityTests(unittest.TestCase):
    def test_document_with_review_page_requires_review(self):
        status, reasons = aggregate_document(["accepted_with_warning", "review"], source_verified=False)
        self.assertEqual(status, "review")
        self.assertTrue(reasons)

    def test_legacy_conversion_failure_requires_review(self):
        status, reasons = aggregate_document(["review"], conversion_status="unavailable")
        self.assertEqual(status, "review")
        self.assertIn("legacy_doc_conversion_requires_manual_recovery", reasons)

    def test_clean_unverified_document_can_only_be_accepted_with_warning(self):
        status, _ = aggregate_document(["accepted"], source_verified=False)
        self.assertEqual(status, "accepted_with_warning")


if __name__ == "__main__":
    unittest.main()
