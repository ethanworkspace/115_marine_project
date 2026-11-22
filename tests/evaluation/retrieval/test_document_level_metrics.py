import unittest

from src.evaluation.retrieval.metrics import recall_at
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class DocumentLevelMetricTests(unittest.TestCase):
    def test_same_document_different_page_is_document_hit(self):
        gold = ResolvedGold("q", required=(GoldEvidence("gold", "doc", 4, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "other-page", "doc", 9),))
        self.assertEqual(recall_at(result, gold, 1, "document"), 1.0)
        self.assertEqual(recall_at(result, gold, 1, "page"), 0.0)

    def test_document_not_found(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "doc", 1, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "x", "other", 1),))
        self.assertEqual(recall_at(result, gold, 10, "document"), 0.0)
