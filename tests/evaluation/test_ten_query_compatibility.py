import unittest
from src.evaluation.edge.recovery19b1 import compatibility
class TenQueryTest(unittest.TestCase):
    def rows(self):return [dict(chunk_id='a',reranker_rank=1,reranker_score=2),dict(chunk_id='b',reranker_rank=2,reranker_score=1)]
    def test_exact_scores_and_order(self):
        r=compatibility(self.rows(),self.rows());self.assertTrue(r['passed']);self.assertEqual(r['max_score_difference'],0)
    def test_rank_change_stops(self):
        r=self.rows();r[0]['reranker_rank']=2;r[1]['reranker_rank']=1
        self.assertFalse(compatibility(self.rows(),r)['passed'])
    def test_candidate_loss_or_NaN_stops(self):
        self.assertFalse(compatibility(self.rows(),self.rows()[:1])['passed'])
        r=self.rows();r[0]['reranker_score']=float('nan');self.assertFalse(compatibility(self.rows(),r)['passed'])
