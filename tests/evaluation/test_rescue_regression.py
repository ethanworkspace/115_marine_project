import unittest

from src.evaluation.rrf import rescue_regression
from tests.evaluation.grounded_baseline_fixtures import hit


class RescueRegressionTests(unittest.TestCase):
    def test_rescue_and_regression_flags(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(rank, f"x{rank}", "d", 1) for rank in range(1, 11)] + [hit(11, "gold", "d", 1)]
        dense = [hit(1, "gold", "d", 1)]
        rrf = [{"chunk_id": "gold", "final_rank": 1}]
        row = rescue_regression(q, bm, dense, rrf)
        self.assertTrue(row["by_k"]["1"]["rescued_bm25_miss"])
        self.assertFalse(row["by_k"]["1"]["introduced_regression_from_dense"])

    def test_worse_than_both_when_both_baselines_hit_but_fusion_misses(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(1, "gold", "d", 1)]
        dense = [hit(1, "gold", "d", 1)]
        rrf = [{"chunk_id": "x", "final_rank": 1}]
        row = rescue_regression(q, bm, dense, rrf)
        self.assertEqual(row["by_k"]["1"]["comparison"], "rrf_worse_than_both")
        self.assertTrue(row["by_k"]["1"]["introduced_regression_from_bm25"])
        self.assertTrue(row["by_k"]["1"]["introduced_regression_from_dense"])

    def test_between_baselines_uses_observed_evidence_ranks(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(1, "gold", "d", 1)]
        dense = [hit(1, "x", "d", 1), hit(2, "y", "d", 1), hit(3, "gold", "d", 1)]
        rrf = [{"chunk_id": "x", "final_rank": 1}, {"chunk_id": "gold", "final_rank": 2}]
        row = rescue_regression(q, bm, dense, rrf)
        self.assertEqual(row["by_k"]["5"]["comparison"], "rrf_between_baselines")
        self.assertEqual(row["by_k"]["5"]["rrf_required_rank_within_k"], 2)


if __name__ == "__main__":
    unittest.main()
