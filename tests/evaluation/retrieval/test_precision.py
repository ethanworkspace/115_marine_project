import unittest

from src.evaluation.retrieval.metrics import precision_at
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class PrecisionTests(unittest.TestCase):
    def test_precision_uses_top_k_and_unique_relevance(self):
        gold = ResolvedGold("q", required=(GoldEvidence("g", "d", 1, "required"),))
        hits = (RankedHit(1, "g", "d", 1), RankedHit(2, "x", "d", 1))
        self.assertEqual(precision_at(RetrievalResult("q", hits), gold, 5, "chunk"), 0.2)

    def test_acceptable_chunk_counts_as_relevant(self):
        gold = ResolvedGold("q", acceptable=(GoldEvidence("a", "d", 1, "acceptable"),))
        result = RetrievalResult("q", (RankedHit(1, "a", "d", 1),))
        self.assertEqual(precision_at(result, gold, 5, "chunk"), 0.2)
