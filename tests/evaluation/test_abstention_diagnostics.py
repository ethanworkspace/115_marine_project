import unittest

from src.evaluation.generation.evaluation import determine_failures


class AbstentionDiagnosticTests(unittest.TestCase):
    def test_evidence_hit_abstention_is_possible_false_abstention(self):
        failures = determine_failures(condition="G1", schema_valid=True, status="insufficient_evidence", required_in_context=True, citation_summary={}, numeric=None)
        self.assertIn("possible_false_abstention", failures)
        self.assertIn("generation_failure_after_retrieval_hit", failures)

    def test_retrieval_miss_abstention_is_not_labeled_answer_hallucination(self):
        failures = determine_failures(condition="G1", schema_valid=True, status="insufficient_evidence", required_in_context=False, citation_summary={}, numeric=None)
        self.assertIn("retrieval_miss", failures)
        self.assertNotIn("answered_without_required_evidence", failures)


if __name__ == "__main__":
    unittest.main()
