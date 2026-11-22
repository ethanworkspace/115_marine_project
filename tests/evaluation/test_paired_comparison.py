import unittest

from src.evaluation.grounded_baselines import error_comparison, paired_comparison
from tests.evaluation.grounded_baseline_fixtures import fake_experiment, hit, question


class PairedComparisonTests(unittest.TestCase):
    def test_only_dense_top1_hit_and_missing_rank_is_null(self):
        q = question()
        e1 = fake_experiment(q, ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10", "c0"])
        e2 = fake_experiment(q, ["c0", "c1", "c2", "c3"])
        e1["full_rankings"]["q1"] = [hit(rank, chunk, f"d{int(chunk[1:]) // 2}", int(chunk[1:]) % 2 + 1)
                                      for rank, chunk in enumerate(["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10", "c0"], start=1)]
        summary, paired, ranks = paired_comparison(e1, e2)
        self.assertEqual(summary["hit@1"]["dense_only_hit"], 1)
        self.assertEqual(summary["hit@5"]["dense_only_hit"], 1)
        self.assertIsNone(ranks[0]["rank_difference_dense_minus_bm25"])
        self.assertEqual(ranks[0]["bm25_rank_status"], "missed_top10")
        failures = error_comparison([], [], paired)
        self.assertEqual(failures["E1_error_distribution"]["unknown"], 0)
        self.assertEqual(failures["paired_failure_groups_by_overlap_bucket"]["medium"]["neither_fail"], 1)


if __name__ == "__main__":
    unittest.main()
