import unittest

from src.ingestion.phase6 import classify_tables


class TableClassificationTests(unittest.TestCase):
    def test_classification_keeps_reasons_and_does_not_auto_reject_false_positive(self):
        pages = [{
            "document_id": "doc", "page_number": 2, "file_checksum": "a" * 64,
            "parser_version": "1", "native_text": "some text", "image_coverage": 0.01,
            "tables": [{
                "table_id": "table-1", "document_id": "doc", "page_number": 2,
                "headers": [], "rows": [], "row_count": 0, "column_count": 0,
                "confidence": 0.0, "warnings": ["header_not_reliably_extracted"],
                "needs_review": True,
            }],
        }]
        result = classify_tables(pages)[0]
        self.assertEqual(result["classification"], "false_positive")
        self.assertTrue(result["classification_reason"])
        self.assertEqual(result["ingestion_status"], "review")
        self.assertFalse(result["classification_is_heuristic"] is False)


if __name__ == "__main__":
    unittest.main()
