import unittest

from src.evaluation.grounded_baselines import _group_reports
from src.evaluation.retrieval.metrics import metric_bundle
from src.evaluation.retrieval.models import GoldEvidence, ResolvedGold, RetrievalResult
from tests.evaluation.grounded_baseline_fixtures import fake_experiment, hit, question


class QueryStyleMetricTests(unittest.TestCase):
    def test_requested_precision_and_ndcg_cutoffs_exist(self):
        result = RetrievalResult("q", (hit(1, "c0", "d0", 1), hit(2, "c1", "d0", 2)))
        gold = ResolvedGold("q", (GoldEvidence("c0", "d0", 1, "required"),))
        scores = metric_bundle(result, gold, "chunk").scores
        for name in ("precision@1", "precision@3", "precision@5", "precision@10",
                     "ndcg@1", "ndcg@3", "ndcg@5", "ndcg@10"):
            self.assertIn(name, scores)

    def test_style_slice_preserves_question_count(self):
        q = question(style="paraphrase")
        row = fake_experiment(q, ["c0", "c1", "c2", "c3"])["rows"][0]
        groups = _group_reports([row], field="query_style")
        self.assertEqual(groups["paraphrase"]["question_count"], 1)


if __name__ == "__main__":
    unittest.main()
