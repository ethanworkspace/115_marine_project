import unittest

from src.evaluation.rrf import RRF_TIE_BREAK, fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit


class RRFTieBreakTests(unittest.TestCase):
    def test_equal_scores_break_by_best_then_bm25_rank_then_dense_rank_then_chunk_id(self):
        corpus = {name: {"chunk_id": name, "document_id": "d", "page": 1} for name in ("a", "b", "c")}
        bm25 = [hit(1, "b", "d", 1), hit(2, "a", "d", 1)]
        dense = [hit(1, "c", "d", 1), hit(2, "a", "d", 1)]
        fused = fuse_ranked_lists(bm25, dense, corpus)
        # b and c have the same RRF score and best rank; BM25 rank precedes Dense rank.
        self.assertEqual([row["chunk_id"] for row in fused], ["a", "b", "c"])
        self.assertEqual(RRF_TIE_BREAK[-1], "chunk_id_ascending")

    def test_chunk_id_is_final_declared_tiebreak(self):
        self.assertEqual(RRF_TIE_BREAK, (
            "rrf_score_descending", "best_individual_rank_ascending",
            "bm25_rank_ascending_nulls_last", "dense_rank_ascending_nulls_last",
            "chunk_id_ascending",
        ))


if __name__ == "__main__":
    unittest.main()
