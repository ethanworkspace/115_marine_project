import unittest
from unittest.mock import patch

from src.evaluation.grounded_baselines import bootstrap_comparison
from tests.evaluation.grounded_baseline_fixtures import fake_experiment, question


class BootstrapCITests(unittest.TestCase):
    def test_paired_ci_is_seeded_and_reports_delta(self):
        q1 = question("q1", chunks=("c0",))
        q2 = question("q2", chunks=("c1",), pages=(("d0", 2),))
        e1 = fake_experiment(q1, ["c0", "c1", "c2", "c3"])["rows"] + fake_experiment(q2, ["c0", "c1", "c2", "c3"])["rows"]
        e2 = fake_experiment(q1, ["c1", "c0", "c2", "c3"])["rows"] + fake_experiment(q2, ["c1", "c0", "c2", "c3"])["rows"]
        with patch("src.evaluation.grounded_baselines.BOOTSTRAP_ITERATIONS", 50):
            result1 = bootstrap_comparison(e1, e2)
            result2 = bootstrap_comparison(e1, e2)
        self.assertEqual(result1, result2)
        self.assertEqual(result1["random_seed"], 12012)
        self.assertIn("E2_minus_E1_paired", result1["metrics"]["chunk"]["recall@5"])


if __name__ == "__main__":
    unittest.main()
