import unittest

from src.evaluation.rrf import CANDIDATE_DEPTH, fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit


class RRFCandidateDepthTests(unittest.TestCase):
    def test_top50_inputs_produce_only_their_union(self):
        corpus = {f"c{i}": {"chunk_id": f"c{i}", "document_id": "d", "page": 1} for i in range(100)}
        bm25 = [hit(rank, f"c{rank-1}", "d", 1) for rank in range(1, CANDIDATE_DEPTH + 1)]
        dense = [hit(rank, f"c{rank+49}", "d", 1) for rank in range(1, CANDIDATE_DEPTH + 1)]
        fused = fuse_ranked_lists(bm25, dense, corpus, top_n=100)
        self.assertEqual(len(fused), 100)
        self.assertEqual({row["chunk_id"] for row in fused}, {f"c{i}" for i in range(100)})

    def test_candidate_list_outside_requested_top50_is_not_fused_by_caller(self):
        corpus = {f"c{i}": {"chunk_id": f"c{i}", "document_id": "d", "page": 1} for i in range(51)}
        full = [hit(rank, f"c{rank-1}", "d", 1) for rank in range(1, 52)]
        fused = fuse_ranked_lists(full[:CANDIDATE_DEPTH], [], corpus, top_n=100)
        self.assertNotIn("c50", {row["chunk_id"] for row in fused})


if __name__ == "__main__":
    unittest.main()
