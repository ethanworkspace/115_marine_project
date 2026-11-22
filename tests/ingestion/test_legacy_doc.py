import hashlib
import tempfile
import unittest
from pathlib import Path

from src.ingestion.parsers.legacy_doc import LegacyDOCParser


class FailedConverter:
    def convert_to_pdf(self, source, output_dir):
        raise RuntimeError("Word COM activation unavailable")


class LegacyDOCParserTests(unittest.TestCase):
    def test_conversion_failure_becomes_manual_review_without_guessed_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.doc"
            path.write_bytes(b"opaque legacy content")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = {"document_id": "doc-legacy", "file_path": "legacy.doc", "checksum": checksum}
            result = LegacyDOCParser(converter=FailedConverter()).parse(path, manifest)

        self.assertEqual(result.conversion_status, "unavailable")
        self.assertTrue(result.needs_review)
        self.assertEqual(result.pages[0].extraction_method, "failed")
        self.assertEqual(result.pages[0].text, "")
        self.assertEqual(result.pages[0].classification, "parser_error")
        self.assertTrue(any("No binary decoding" in warning for warning in result.pages[0].warnings))


if __name__ == "__main__":
    unittest.main()
