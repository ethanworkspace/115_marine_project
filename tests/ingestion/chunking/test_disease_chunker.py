import unittest

from src.ingestion.chunking.disease import chunk_disease
from src.ingestion.chunking.common import TextUnit
from tests.ingestion.chunking.helpers import document, factory, page, run_single


class DiseaseChunkerTests(unittest.TestCase):
    def test_explicit_disease_headings_are_kept_separate(self):
        text = "（一）愛德華氏病\n1. 病原\n細菌。\n2. 病徵\n食慾下降。\n（二）赤鰭病\n病原：細菌。\n診斷：觀察病灶。"
        result = run_single(chunk_disease, document(title="魚病資料"), text)
        parents = [r for r in result.records if r["chunk_type"] == "parent"]
        self.assertIn("愛德華氏病", {r["disease"] for r in parents})
        self.assertIn("赤鰭病", {r["disease"] for r in parents})
        for child in (r for r in result.records if r["chunk_type"] == "child"):
            parent = next(p for p in parents if p["chunk_id"] == child["parent_chunk_id"])
            self.assertEqual(child["disease"], parent["disease"])

    def test_disease_is_not_inferred_when_heading_is_missing(self):
        result = run_single(chunk_disease, document(title="疾病資料"), "症狀與防治資訊。")
        self.assertTrue(all(r["disease"] is None for r in result.records))

    def test_prose_line_ending_in_disease_word_is_not_an_entity(self):
        text = "主要感染部位包括鰓部，嚴重罹病時症狀較明顯。\n這是一般說明段落。"
        result = run_single(chunk_disease, document(title="疾病資料"), text)
        self.assertTrue(all(r["disease"] is None for r in result.records))

    def test_broad_disease_category_uses_page_local_parent_context(self):
        pages = [
            page("八、台灣地區常見寄生蟲病\n" + "病害描述。" * 30, 1),
            page("延續文字。" * 30, 2),
        ]
        result = factory()
        chunk_disease(document(title="疾病資料"), TextUnit(pages), result)
        parents = [r for r in result.records if r["chunk_type"] == "parent"]
        self.assertEqual({(r["page_start"], r["page_end"]) for r in parents}, {(1, 1), (2, 2)})
        self.assertTrue(all(r["disease"] is None for r in parents))


if __name__ == "__main__":
    unittest.main()
