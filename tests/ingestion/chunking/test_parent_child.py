import unittest

from src.ingestion.chunking.manual import chunk_manual
from tests.ingestion.chunking.helpers import document, run_single


class ParentChildTests(unittest.TestCase):
    def test_every_child_has_parent_and_matching_document(self):
        result = run_single(chunk_manual, document(title="手冊"), "第一章 內容\n說明段落。")
        parents = {r["chunk_id"]: r for r in result.records if r["chunk_type"] == "parent"}
        children = [r for r in result.records if r["chunk_type"] == "child"]
        self.assertTrue(children)
        for child in children:
            self.assertIn(child["parent_chunk_id"], parents)
            self.assertEqual(child["document_id"], parents[child["parent_chunk_id"]]["document_id"])


if __name__ == "__main__":
    unittest.main()
