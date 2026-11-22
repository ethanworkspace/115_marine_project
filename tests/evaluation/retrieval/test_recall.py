import unittest

from src.evaluation.retrieval.metrics import recall_at
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.gold = ResolvedGold("q", required=(GoldEvidence("g1", "d1", 1, "required"),))

    def test_gold_at_rank_one(self):
        result = RetrievalResult("q", (RankedHit(1, "g1", "d1", 1),))
        self.assertEqual(recall_at(result, self.gold, 1, "chunk"), 1.0)

    def test_gold_at_rank_five(self):
        hits = tuple(RankedHit(i, f"x{i}" if i < 5 else "g1", "d1", 1) for i in range(1, 6))
        self.assertEqual(recall_at(RetrievalResult("q", hits), self.gold, 5, "chunk"), 1.0)
        self.assertEqual(recall_at(RetrievalResult("q", hits), self.gold, 3, "chunk"), 0.0)

    def test_gold_not_found(self):
        result = RetrievalResult("q", (RankedHit(1, "x", "d1", 1),))
        self.assertEqual(recall_at(result, self.gold, 10, "chunk"), 0.0)
