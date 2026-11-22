import unittest

from src.evaluation.rrf import fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit


class RRFDeterminismTests(unittest.TestCase):
    def test_input_order_does_not_change_result(self):
        corpus = {name: {"chunk_id": name, "document_id": "d", "page": 1} for name in ("a", "b", "c")}
        bm25 = [hit(1, "a", "d", 1), hit(2, "b", "d", 1)]
        dense = [hit(1, "c", "d", 1), hit(2, "b", "d", 1)]
        first = fuse_ranked_lists(bm25, dense, corpus)
        second = fuse_ranked_lists(list(bm25), list(dense), corpus)
        self.assertEqual([(row["chunk_id"], row["rrf_score"]) for row in first],
                         [(row["chunk_id"], row["rrf_score"]) for row in second])

    def test_invalid_noncontiguous_rank_fails(self):
        with self.assertRaises(ValueError):
            fuse_ranked_lists([hit(2, "a", "d", 1)], [], {"a": {"chunk_id": "a", "document_id": "d", "page": 1}})


if __name__ == "__main__":
    unittest.main()
