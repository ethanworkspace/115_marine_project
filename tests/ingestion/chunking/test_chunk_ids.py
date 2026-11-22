import unittest

from src.ingestion.chunking.common import stable_chunk_id


class ChunkIdTests(unittest.TestCase):
    def test_same_document_span_strategy_version_and_text_is_stable(self):
        values = dict(document_id="d1", source_span_ids=["s1", "s2"], strategy="manual",
                      version="2", chunk_type="child", content_checksum="abc", parent_chunk_id="p1")
        self.assertEqual(stable_chunk_id(**values), stable_chunk_id(**values))

    def test_content_or_source_change_changes_id(self):
        values = dict(document_id="d1", source_span_ids=["s1"], strategy="fallback",
                      version="2", chunk_type="child", content_checksum="abc", parent_chunk_id="p1")
        self.assertNotEqual(stable_chunk_id(**values), stable_chunk_id(**{**values, "content_checksum": "def"}))


if __name__ == "__main__":
    unittest.main()
