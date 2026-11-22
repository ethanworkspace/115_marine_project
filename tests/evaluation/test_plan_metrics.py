import unittest

from src.evaluation.phase20_protocol import EDGE_WEIGHTS, QUALITY_WEIGHTS


class PlanMetricTests(unittest.TestCase):
    def test_primary_metric_weights_match_plan(self):
        self.assertAlmostEqual(sum(QUALITY_WEIGHTS.values()), 0.70)
        self.assertAlmostEqual(sum(EDGE_WEIGHTS.values()), 0.30)
        self.assertEqual(set(QUALITY_WEIGHTS), {
            "faithfulness", "plan_answer_relevance", "arithmetic_accuracy", "plan_ifr"
        })


if __name__ == "__main__":
    unittest.main()
