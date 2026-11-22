import unittest

from src.evaluation.grounded_baselines import fairness_validation
from tests.evaluation.grounded_baseline_fixtures import corpus_rows, fake_experiment, question


class SameQuestionsTests(unittest.TestCase):
    def test_fairness_requires_same_questions_corpus_topk_metrics_and_evidence(self):
        q = question()
        rows = corpus_rows()
        common = {"retrieval_corpus_chunk_ids_sha256": "chunks", "required_evidence_resolution_sha256": "evidence",
                  "top_k": [1, 3, 5, 10], "metric_implementation": "same", "gold_evidence_used_for_ranking": False}
        e1 = {"rows": [fake_experiment(q, ["c0", "c1", "c2", "c3"])["rows"][0]], "manifest": common}
        e2 = {"rows": [fake_experiment(q, ["c1", "c0", "c2", "c3"])["rows"][0]], "manifest": common}
        frozen = {"corpus": rows, "corpus_chunk_ids_sha256": "chunks", "evidence_resolution_sha256": "evidence", "questions": [q]}
        result = fairness_validation(e1, e2, frozen)
        self.assertEqual(result["status"], "passed")
        e2["manifest"] = {**common, "top_k": [1, 3, 5]}
        with self.assertRaisesRegex(RuntimeError, "fairness check failed"):
            fairness_validation(e1, e2, frozen)


if __name__ == "__main__":
    unittest.main()
