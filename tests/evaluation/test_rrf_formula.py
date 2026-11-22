import unittest

from src.evaluation.rrf import fuse_ranked_lists
from tests.evaluation.grounded_baseline_fixtures import hit


class RRFormulaTests(unittest.TestCase):
    def test_standard_reciprocal_rank_formula_ignores_raw_scores(self):
        rows = [
            {"chunk_id": "a", "document_id": "d1", "page_start": 1, "page_end": 1},
            {"chunk_id": "b", "document_id": "d1", "page_start": 2, "page_end": 2},
            {"chunk_id": "c", "document_id": "d1", "page_start": 3, "page_end": 3},
        ]
        fused = fuse_ranked_lists([hit(1, "a", "d1", 1, 999)],
                                  [hit(1, "c", "d1", 3, 0), hit(2, "a", "d1", 1, -400)],
                                  {row["chunk_id"]: row for row in rows})
        self.assertAlmostEqual(fused[0]["rrf_score"], 1 / 61 + 1 / 62)
        self.assertEqual(fused[0]["bm25_rank"], 1)
        self.assertEqual(fused[0]["dense_rank"], 2)

    def test_absent_retriever_contributes_zero_and_null_rank(self):
        corpus = {"a": {"chunk_id": "a", "document_id": "d1", "page": 1}}
        row = fuse_ranked_lists([hit(1, "a", "d1", 1)], [], corpus)[0]
        self.assertIsNone(row["dense_rank"])
        self.assertEqual(row["dense_rrf_contribution"], 0.0)
        self.assertAlmostEqual(row["rrf_score"], 1 / 61)


if __name__ == "__main__":
    unittest.main()
