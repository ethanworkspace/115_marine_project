import unittest

from src.evaluation.rrf import fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit


class RRFEqualWeightTests(unittest.TestCase):
    def test_both_retrievers_use_equal_unit_weights(self):
        corpus = {"a": {"chunk_id": "a", "document_id": "d", "page": 1}}
        row = fuse_ranked_lists([hit(1, "a", "d", 1)], [hit(1, "a", "d", 1)], corpus)[0]
        self.assertEqual(row["bm25_rrf_contribution"], row["dense_rrf_contribution"])

    def test_non_equal_weight_is_rejected(self):
        with self.assertRaises(ValueError):
            fuse_ranked_lists([], [], {}, bm25_weight=2.0)


if __name__ == "__main__":
    unittest.main()
