import unittest

from src.evaluation.phase10_recovery import coverage_gain


class CoverageGainTests(unittest.TestCase):
    def test_transitions_grouping_and_recovery_action_are_reported(self):
        previous = [{"question_id": "q", "species_candidate": "鱸魚", "category": "disease",
                     "evidence_mapping_status": "unmapped"}]
        current = [{"question_id": "q", "species_candidate": "鱸魚", "category": "disease",
                    "evidence_mapping_status": "high_confidence",
                    "expected_facts": [{"mapped_documents": ["d"]}]}]
        report = coverage_gain(previous, current, recovery_actions={"d": "missing_source_acquisition"})
        self.assertEqual(report["net_exact_high_gain"], 1)
        self.assertEqual(report["transitions"]["unmapped->high_confidence"], 1)
        self.assertEqual(report["by_species"]["鱸魚"]["current"]["high_confidence"], 1)
        self.assertEqual(report["gain_by_recovery_action"]["missing_source_acquisition"]["upgraded_questions"], 1)

    def test_question_identity_must_match(self):
        with self.assertRaises(ValueError):
            coverage_gain([{"question_id": "a"}], [{"question_id": "b"}])


if __name__ == "__main__":
    unittest.main()
