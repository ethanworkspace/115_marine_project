import hashlib
import unittest

from src.ingestion.chunking.table import chunk_accepted_tables
from tests.ingestion.chunking.helpers import CONFIG, document, page
from src.ingestion.chunking.common import ChunkFactory


class TableChunkerTests(unittest.TestCase):
    def test_header_units_and_rows_are_preserved(self):
        table = {"table_id": "t1", "document_id": "doc-1", "page_number": 1,
                 "caption": "水質範圍", "headers": ["溫度", "鹽度"], "units": ["℃", "ppt"],
                 "rows": [["20", "10"], ["25", "15"]], "footnotes": ["參考值"],
                 "parser_name": "test", "confidence": 0.9, "ingestion_status": "accepted",
                 "classification": "simple_table", "warnings": []}
        source = page("表格頁")
        source["tables"] = [table]
        factory = ChunkFactory(config=CONFIG, span_registry={})
        count = chunk_accepted_tables(document(), [source], factory)
        self.assertEqual(count, 1)
        records = factory.records
        self.assertIn("溫度 (℃) | 鹽度 (ppt)", records[0]["text"])
        self.assertEqual(records[0]["table_data"]["rows"], table["rows"])
        self.assertIn("參考值", records[0]["text"])

    def test_review_table_is_not_admitted(self):
        source = page("表格頁")
        source["tables"] = [{"table_id": "t2", "document_id": "doc-1", "page_number": 1,
                             "headers": ["h"], "rows": [["v"]], "ingestion_status": "review",
                             "classification": "simple_table"}]
        factory = ChunkFactory(config=CONFIG, span_registry={})
        self.assertEqual(chunk_accepted_tables(document(), [source], factory), 0)
        self.assertEqual(factory.records, [])


if __name__ == "__main__":
    unittest.main()
