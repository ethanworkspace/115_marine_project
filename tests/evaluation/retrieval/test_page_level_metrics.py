import unittest

from src.evaluation.retrieval.metrics import ndcg_at, precision_at, recall_at
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class PageLevelMetricTests(unittest.TestCase):
    def test_same_page_different_chunk_is_page_hit_only(self):
        gold = ResolvedGold("q", required=(GoldEvidence("gold-chunk", "doc", 4, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "other-chunk", "doc", 4),))
        self.assertEqual(recall_at(result, gold, 1, "page"), 1.0)
        self.assertEqual(recall_at(result, gold, 1, "chunk"), 0.0)

    def test_gold_page_not_found(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "doc", 4, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "x", "doc", 5),))
        self.assertEqual(recall_at(result, gold, 1, "page"), 0.0)

    def test_multpage_chunk_keeps_page_precision_and_ndcg_bounded(self):
        gold = ResolvedGold("q", required=(
            GoldEvidence("g1", "doc", 1, "required"),
            GoldEvidence("g2", "doc", 2, "required"),
        ))
        result = RetrievalResult("q", (RankedHit(1, "span", "doc", 1, page_end=2),))
        self.assertEqual(recall_at(result, gold, 1, "page"), 1.0)
        self.assertEqual(precision_at(result, gold, 1, "page"), 1.0)
        self.assertEqual(ndcg_at(result, gold, 1, "page"), 1.0)
