import unittest

from src.ingestion.chunking.common import ChunkFactory, TextUnit
from tests.ingestion.chunking.helpers import CONFIG, document, page


class ChunkProvenanceTests(unittest.TestCase):
    def test_page_checksum_and_parser_provenance_resolve_from_span(self):
        source = page("有來源的文字", 3)
        spans = {}
        factory = ChunkFactory(config=CONFIG, span_registry=spans)
        record = factory.add_text(document=document(), unit=TextUnit([source]), start=0,
                                  end=len(source["selected_text"]), strategy="fallback",
                                  chunk_type="parent")
        span = spans[record["source_span_ids"][0]]
        self.assertEqual(span["document_id"], record["document_id"])
        self.assertEqual(span["page_number"], 3)
        self.assertEqual(span["file_checksum"], source["file_checksum"])
        self.assertEqual(span["parser_name"], "test-parser")


if __name__ == "__main__":
    unittest.main()
