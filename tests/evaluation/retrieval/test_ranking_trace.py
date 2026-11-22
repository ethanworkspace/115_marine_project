import unittest

from src.evaluation.retrieval.models import RankedHit
from src.evaluation.retrieval.models import GoldEvidence, ResolvedGold, RetrievalQuery, RetrievalResult
from src.evaluation.retrieval.report import ranking_trace


class RankingTraceShapeTests(unittest.TestCase):
    def test_ranked_hit_has_trace_fields(self):
        hit = RankedHit(1, "chunk", "doc", 2, 0.7, 0.9)
        self.assertEqual((hit.rank, hit.chunk_id, hit.document_id, hit.page), (1, "chunk", "doc", 2))
        self.assertEqual((hit.raw_score, hit.normalized_score), (0.7, 0.9))

    def test_trace_marks_chunk_page_document_matches(self):
        query = RetrievalQuery("q", "question")
        gold = ResolvedGold("q", required=(GoldEvidence("gold", "doc", 2, "required"),))
        result = RetrievalResult("q", (RankedHit(1, "other-chunk", "doc", 2, 0.5, 0.7),))
        trace = ranking_trace(query, result, gold)[0]
        self.assertFalse(trace["chunk_match"])
        self.assertTrue(trace["page_match"])
        self.assertTrue(trace["document_match"])
        self.assertFalse(trace["is_required_gold"])
