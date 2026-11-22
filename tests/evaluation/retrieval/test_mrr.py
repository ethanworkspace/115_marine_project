import unittest

from src.evaluation.retrieval.metrics import reciprocal_rank
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class MRRTests(unittest.TestCase):
    def test_rank_one_and_rank_five(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "d", 1, "required"),))
        self.assertEqual(reciprocal_rank(RetrievalResult("q", (RankedHit(1, "g", "d", 1),)), gold, "chunk"), 1.0)
        hits = tuple(RankedHit(i, "g" if i == 5 else str(i), "d", 1) for i in range(1, 6))
        self.assertEqual(reciprocal_rank(RetrievalResult("q", hits), gold, "chunk"), 0.2)

    def test_no_relevant_returns_zero(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "d", 1, "required"),))
        self.assertEqual(reciprocal_rank(RetrievalResult("q", ()), gold, "chunk"), 0.0)
