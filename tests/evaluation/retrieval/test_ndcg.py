import unittest

from src.evaluation.retrieval.metrics import ndcg_at
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class NDCGTests(unittest.TestCase):
    def test_rank_one_is_ideal(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "d", 1, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "g", "d", 1),))
        self.assertEqual(ndcg_at(result, gold, 5, "chunk"), 1.0)

    def test_lower_rank_has_discount(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "d", 1, "required"),))
        hits = tuple(RankedHit(i, "g" if i == 5 else f"x{i}", "d", 1) for i in range(1, 6))
        self.assertLess(ndcg_at(RetrievalResult("q", hits), gold, 5, "chunk"), 1.0)
