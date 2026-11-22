import unittest

from src.evaluation.retrieval.metrics import required_evidence_coverage
from src.evaluation.retrieval.models import GoldEvidence, RankedHit, ResolvedGold, RetrievalResult


class RequiredEvidenceCoverageTests(unittest.TestCase):
    def test_multi_document_partial_is_not_full_success(self):
        gold = ResolvedGold("q", required=(GoldEvidence("a", "d1", 1, "required"), GoldEvidence("b", "d2", 3, "required")))
        result = RetrievalResult("q", (RankedHit(1, "a", "d1", 1),))
        coverage = required_evidence_coverage(result, gold)
        self.assertTrue(coverage["required_hit"])
        self.assertFalse(coverage["all_required_recalled"])
        self.assertTrue(coverage["multi_document_partial"])

    def test_acceptable_hit_is_reported_separately(self):
        gold = ResolvedGold("q", acceptable=(GoldEvidence("alt", "d1", 1, "acceptable"),))
        coverage = required_evidence_coverage(RetrievalResult("q", (RankedHit(1, "alt", "d1", 1),)), gold)
        self.assertTrue(coverage["acceptable_hit"])
        self.assertFalse(coverage["required_hit"])
