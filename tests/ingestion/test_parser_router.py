import unittest
from pathlib import Path

from src.ingestion.parsers.base import UnsupportedFormatError
from src.ingestion.parsers.router import ParserRouter


class ParserRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = ParserRouter(config={"pdf": {"extract_tables": False}})

    def test_supported_formats_route_to_explicit_parsers(self):
        expected = {
            ".pdf": "PDFParser",
            ".docx": "DOCXParser",
            ".doc": "LegacyDOCParser",
            ".odt": "ODTParser",
            ".txt": "PlainTextParser",
            ".md": "PlainTextParser",
        }
        for extension, class_name in expected.items():
            with self.subTest(extension=extension):
                self.assertEqual(type(self.router.route(Path("fixture" + extension))).__name__, class_name)

    def test_unknown_format_fails_explicitly(self):
        with self.assertRaisesRegex(UnsupportedFormatError, "unsupported document format"):
            self.router.route("attachment.xlsx")


if __name__ == "__main__":
    unittest.main()
