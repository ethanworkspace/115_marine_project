import hashlib
import unittest

from src.ingestion.models import PageRecord
from src.ingestion.parsers.ocr import OCRBackend, OCRResult, apply_ocr_image, evaluate_ocr_quality


class FakeBackend(OCRBackend):
    name = "fake"
    version = "test"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def recognize(self, image_bytes):
        if self.error:
            raise self.error
        return self.result


class OCRQualityTests(unittest.TestCase):
    def make_page(self):
        return PageRecord(
            "doc-1", hashlib.sha256(b"source").hexdigest(), 1,
            "native snippet", "native snippet", "", "native", 0.8,
            [], [], "test", "1", needs_review=True, classification="ocr_candidate",
        )

    def test_quality_gate_passes_clean_text_and_rejects_garbage(self):
        clean = evaluate_ocr_quality("This is a clear recognized sentence with enough characters.", 0.9)
        garbage = evaluate_ocr_quality("\ufffd\ufffd\x01", 0.1)
        self.assertEqual(clean.status, "pass")
        self.assertEqual(garbage.status, "reject")

    def test_ocr_failure_does_not_claim_success_or_change_native_text(self):
        page = self.make_page()
        status = apply_ocr_image(page, b"image", FakeBackend(error=RuntimeError("OCR crash")))
        self.assertEqual(page.ocr_quality_status, "failed")
        self.assertEqual(page.text, "native snippet")
        self.assertEqual(page.native_text, "native snippet")
        self.assertTrue(page.needs_review)
        self.assertEqual(status.status, "reject")

    def test_rejected_ocr_text_is_not_promoted_to_primary_text(self):
        page = self.make_page()
        result = OCRResult("\ufffd\x01\ufffd", 0.1, "fake", "test", [])
        status = apply_ocr_image(page, b"image", FakeBackend(result=result))
        self.assertEqual(status.status, "reject")
        self.assertEqual(page.ocr_text, result.text)
        self.assertEqual(page.text, "native snippet")
        self.assertEqual(page.extraction_method, "failed")

    def test_unavailable_backend_is_explicit(self):
        page = self.make_page()
        apply_ocr_image(page, b"", None)
        self.assertEqual(page.ocr_quality_status, "backend_unavailable")
        self.assertTrue(any("backend_unavailable" in warning for warning in page.warnings))


if __name__ == "__main__":
    unittest.main()
