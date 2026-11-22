import unittest

from src.evaluation.generation.evaluation import determine_failures


class FailureAttributionTests(unittest.TestCase):
    def test_answer_without_required_evidence_is_diagnostic_only(self):
        failures = determine_failures(condition="G1", schema_valid=True, status="answered", required_in_context=False, citation_summary={}, numeric=None)
        self.assertIn("retrieval_miss", failures)
        self.assertIn("answered_without_required_evidence", failures)
        self.assertNotIn("hallucination", failures)

    def test_successful_answer_is_not_a_failure_taxonomy_unknown(self):
        failures = determine_failures(condition="G1", schema_valid=True, status="answered", required_in_context=True, citation_summary={}, numeric=None)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
