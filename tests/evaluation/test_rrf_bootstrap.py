import unittest

from src.evaluation.rrf import paired_bootstrap_rrf


def row(qid, offset):
    metrics = {}
    for granularity in ("chunk", "page", "document"):
        metrics[granularity] = {
            "recall@5": 0.1 + offset, "recall@10": 0.2 + offset,
            "mrr": 0.3 + offset, "ndcg@10": 0.4 + offset,
        }
    return {"question_id": qid, "metrics": metrics}


class RRFBootstrapTests(unittest.TestCase):
    def test_paired_ci_is_repeatable_and_contains_reported_delta(self):
        e1 = [row("q1", 0), row("q2", 0.1)]
        e2 = [row("q1", 0.02), row("q2", 0.12)]
        e3 = [row("q1", 0.05), row("q2", 0.15)]
        first = paired_bootstrap_rrf(e1, e2, e3, seed=12012, iterations=100)
        second = paired_bootstrap_rrf(e1, e2, e3, seed=12012, iterations=100)
        self.assertEqual(first, second)
        result = first["metrics"]["chunk"]["recall@5"]
        self.assertAlmostEqual(result["E3_minus_E1_point_estimate"], 0.05)
        self.assertAlmostEqual(result["E3_minus_E2_point_estimate"], 0.03)

    def test_mismatched_question_ids_fail(self):
        with self.assertRaises(ValueError):
            paired_bootstrap_rrf([row("a", 0)], [row("b", 0)], [row("a", 0)], iterations=1)


if __name__ == "__main__":
    unittest.main()
