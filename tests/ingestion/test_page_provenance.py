import hashlib
import json
import unittest
from pathlib import Path

from src.ingestion.models import PageRecord, merge_accepted_ocr


class PageProvenanceTests(unittest.TestCase):
    def make_page(self):
        return PageRecord(
            document_id="doc-1",
            file_checksum=hashlib.sha256(b"source").hexdigest(),
            page_number=3,
            text="native source text",
            native_text="native source text",
            ocr_text="",
            extraction_method="native",
            extraction_confidence=0.9,
            tables=[], images=[], parser_name="test", parser_version="1",
            classification="ocr_candidate",
        )

    def test_provenance_fields_are_mandatory_and_serialized(self):
        page = self.make_page()
        record = page.to_dict()
        for key in ("document_id", "file_checksum", "page_number", "parser_name", "parser_version", "extraction_method", "extraction_confidence"):
            self.assertIn(key, record)
        self.assertEqual(record["page_number"], 3)

    def test_native_text_is_never_overwritten_by_accepted_ocr(self):
        page = self.make_page()
        merge_accepted_ocr(page, "OCR recognized words")
        self.assertEqual(page.native_text, "native source text")
        self.assertEqual(page.ocr_text, "OCR recognized words")
        self.assertIn("native source text", page.text)
        self.assertIn("OCR recognized words", page.text)

    def test_unknown_page_requires_manual_review(self):
        with self.assertRaisesRegex(ValueError, "without a physical page number"):
            PageRecord(
                "doc-1", hashlib.sha256(b"x").hexdigest(), None, "", "", "", "manual", 0.0,
                [], [], "test", "1", needs_review=False,
            )

    def test_page_schema_declares_required_provenance_and_method_enum(self):
        root = Path(__file__).resolve().parents[2]
        schema = json.loads((root / "schemas" / "page.schema.json").read_text(encoding="utf-8"))
        record = self.make_page().to_dict()
        self.assertTrue(set(schema["required"]).issubset(record))
        self.assertIn(record["extraction_method"], schema["properties"]["extraction_method"]["enum"])


if __name__ == "__main__":
    unittest.main()
