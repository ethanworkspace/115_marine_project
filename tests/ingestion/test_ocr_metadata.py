import hashlib
import unittest

from src.ingestion.models import PageRecord
from src.ingestion.parsers.ocr import OCRBackend, OCRResult, apply_ocr_image, evaluate_ocr_quality


class _Backend(OCRBackend):
    name = "test-ocr"
    version = "1.2"

    def recognize(self, image_bytes):
        return OCRResult("TILAPIA oxygen 5 mg/L, water temperature 28 degC, concentration 2 ppm.", 0.98, self.name, self.version, [], ["chi_tra", "eng"])


class OCRMetadataTests(unittest.TestCase):
    def test_native_text_is_preserved_and_ocr_provenance_is_complete(self):
        native = "native source text"
        page = PageRecord(
            "doc", hashlib.sha256(b"source").hexdigest(), 3, native, native, "",
            "native", 0.9, [], [], "test", "1", needs_review=True,
            classification="ocr_candidate",
        )
        result = apply_ocr_image(page, b"png", _Backend())
        self.assertEqual(page.native_text, native)
        self.assertTrue(page.ocr_text.startswith("TILAPIA"))
        self.assertIn(native, page.selected_text)
        self.assertIn(page.ocr_text, page.selected_text)
        self.assertEqual(page.ocr_backend, "test-ocr")
        self.assertEqual(page.ocr_backend_version, "1.2")
        self.assertEqual(page.ocr_languages, ["chi_tra", "eng"])
        self.assertEqual(result.status, "pass")

    def test_ocr_quality_reports_numbers_units_and_domain_terms(self):
        report = evaluate_ocr_quality("TILAPIA oxygen 5 mg/L, water temperature 28 degC, concentration 2 ppm.", 0.98)
        values = report.to_dict()
        self.assertGreaterEqual(values["number_token_count"], 3)
        self.assertGreaterEqual(values["unit_token_count"], 3)
        self.assertGreaterEqual(values["domain_term_matches"], 1)


if __name__ == "__main__":
    unittest.main()
