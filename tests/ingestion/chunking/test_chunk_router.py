import unittest

from src.ingestion.chunking.router import choose_strategy
from tests.ingestion.chunking.helpers import document, page


class ChunkRouterTests(unittest.TestCase):
    def test_legal_document_with_articles_routes_to_regulation(self):
        doc = document(title="漁業法", document_type="law")
        pages = [page("第一章 總則\n第一條 本法規定。\n第二條 定義如下。")]
        self.assertEqual(choose_strategy(doc, pages).strategy, "regulation")

    def test_manual_uses_heading_structure(self):
        doc = document(title="水產養殖技術手冊")
        pages = [page("第一章 介紹\n第一節 管理\n內容\n第二節 水質\n內容")]
        self.assertEqual(choose_strategy(doc, pages).strategy, "manual")

    def test_unknown_document_routes_to_fallback_with_warning(self):
        decision = choose_strategy(document(), [page("沒有明確結構的文字")])
        self.assertEqual(decision.strategy, "fallback")
        self.assertTrue(decision.warning)


if __name__ == "__main__":
    unittest.main()
