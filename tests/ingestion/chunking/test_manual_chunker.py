import unittest

from src.ingestion.chunking.manual import chunk_manual
from tests.ingestion.chunking.helpers import document, run_single


class ManualChunkerTests(unittest.TestCase):
    def test_children_remain_in_heading_parent(self):
        text = "第一章 飼養\n第一節 水質\n" + ("水質管理內容。" * 18) + "\n第二節 飼料\n" + ("飼料管理內容。" * 18)
        result = run_single(chunk_manual, document(title="養殖手冊"), text)
        parents = {r["chunk_id"]: r for r in result.records if r["chunk_type"] == "parent"}
        children = [r for r in result.records if r["chunk_type"] == "child"]
        self.assertGreaterEqual(len(parents), 3)
        self.assertTrue(children)
        for child in children:
            self.assertEqual(child["section"], parents[child["parent_chunk_id"]]["section"])


if __name__ == "__main__":
    unittest.main()
