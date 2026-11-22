import unittest

from src.evaluation.rrf import candidate_union_oracle, summarize_oracle
from tests.evaluation.grounded_baseline_fixtures import hit


class CandidateUnionOracleTests(unittest.TestCase):
    def test_union_hit_is_not_confused_with_rrf_hit(self):
        q = {"question_id": "q", "required_chunks": ["gold"]}
        bm = [hit(1, "gold", "d", 1)]
        dense = [hit(1, "other", "d", 1)]
        fused = [{"chunk_id": "other"}]
        row = candidate_union_oracle(q, bm, dense, fused)
        self.assertTrue(row["1"]["candidate_union_oracle_hit"])
        self.assertFalse(row["1"]["rrf_required_hit"])
        self.assertTrue(row["1"]["oracle_to_rrf_hit_gap"])
        summary = summarize_oracle([row])
        self.assertEqual(summary["type"], "candidate_union_oracle")
        self.assertEqual(summary["by_k"]["1"]["hit_comparison"]["oracle_minus_rrf_net_gap_count"], 1)


if __name__ == "__main__":
    unittest.main()
