import unittest

from src.evaluation.rrf import rank_movement
from tests.evaluation.grounded_baseline_fixtures import hit


class RankMovementTests(unittest.TestCase):
    def test_missing_from_both_top50_is_null_not_rank51(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(rank, f"b{rank}", "d", 1) for rank in range(1, 51)]
        dense = [hit(rank, f"d{rank}", "d", 1) for rank in range(1, 51)]
        rows = rank_movement(q, bm, dense, [])
        self.assertIsNone(rows[0]["bm25_rank_top50"])
        self.assertIsNone(rows[0]["dense_rank_top50"])
        self.assertIsNone(rows[0]["rrf_rank"])
        self.assertIsNone(rows[0]["rank_delta_vs_best"])

    def test_candidate_and_fused_ranks_are_explicit(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(1, "gold", "d", 1)]
        fused = [{"chunk_id": "gold", "final_rank": 4}]
        row = rank_movement(q, bm, [], fused)[0]
        self.assertEqual(row["rrf_rank"], 4)
        self.assertEqual(row["rank_delta_vs_best"], 3)


if __name__ == "__main__":
    unittest.main()
