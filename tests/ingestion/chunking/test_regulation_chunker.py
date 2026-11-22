import unittest

from src.ingestion.chunking.regulation import chunk_regulation
from tests.ingestion.chunking.helpers import document, run_single


class RegulationChunkerTests(unittest.TestCase):
    def test_article_boundaries_and_children_stay_inside_parent_article(self):
        text = "第一章 總則\n第一條 本法目的。\n第二條 本法名詞定義。\n第三條 本法施行。"
        result = run_single(chunk_regulation, document(title="漁業法", document_type="law"), text)
        parents = {r["chunk_id"]: r for r in result.records if r["chunk_type"] == "parent"}
        children = [r for r in result.records if r["chunk_type"] == "child"]
        self.assertEqual({r["article"] for r in parents.values() if r["article"]}, {"第一條", "第二條", "第三條"})
        self.assertTrue(children)
        for child in children:
            parent = parents[child["parent_chunk_id"]]
            self.assertEqual(child["article"], parent["article"])
            if child["article"]:
                self.assertIn(child["article"], child["text"])


if __name__ == "__main__":
    unittest.main()
