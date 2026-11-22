import unittest

from src.ingestion.gate import apply_ingestion_status, can_index, evaluate_page


class IngestionGateTests(unittest.TestCase):
    def test_review_and_rejected_records_cannot_be_indexed(self):
        for status in ("review", "rejected"):
            record = apply_ingestion_status({"document_id": "doc"}, status, ["needs_check"])
            self.assertFalse(can_index(record))

    def test_accepted_records_are_eligible_for_future_chunking(self):
        for status in ("accepted", "accepted_with_warning"):
            self.assertTrue(can_index({"ingestion_status": status}))

    def test_backend_unavailable_ocr_candidate_requires_review(self):
        record = {
            "document_id": "doc", "file_checksum": "a" * 64, "page_number": 1,
            "native_text": "", "text": "", "selected_text": "", "ocr_text": "",
            "classification": "ocr_candidate", "extraction_method": "manual",
            "ocr_quality_status": "backend_unavailable", "needs_review": True,
        }
        status, _ = evaluate_page(record)
        self.assertEqual(status, "review")

    def test_image_or_chart_without_text_requires_review_not_rejection(self):
        record = {
            "document_id": "doc", "file_checksum": "a" * 64, "page_number": 1,
            "native_text": "", "text": "", "selected_text": "", "ocr_text": "",
            "classification": "image_or_chart", "extraction_method": "manual",
            "ocr_quality_status": "not_run", "needs_review": True,
        }
        status, _ = evaluate_page(record)
        self.assertEqual(status, "review")


if __name__ == "__main__":
    unittest.main()
