import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.ingestion.checksum import sha256_file
from src.ingestion.parsers.pdf import PDFParser


class PDFParserTests(unittest.TestCase):
    def test_page_numbers_and_native_text_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "two-pages.pdf"
            document = pymupdf.open()
            for text in ("Page one native content", "Page two native content"):
                page = document.new_page()
                page.insert_text((72, 72), text)
            document.save(path)
            document.close()
            manifest = {"document_id": "doc-1", "file_path": str(path), "checksum": sha256_file(path)}
            parsed = PDFParser({"pdf": {"extract_tables": False}}).parse(path, manifest)

        self.assertEqual([page.page_number for page in parsed.pages], [1, 2])
        self.assertIn("Page one", parsed.pages[0].native_text)
        self.assertEqual(parsed.pages[0].text, parsed.pages[0].native_text)
        self.assertTrue(all(page.file_checksum == parsed.file_checksum for page in parsed.pages))


if __name__ == "__main__":
    unittest.main()
