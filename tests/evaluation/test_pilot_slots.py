import unittest

from src.evaluation.pilot import build_pilot_slots


class PilotSlotTests(unittest.TestCase):
    def test_slots_are_blank_and_unverified_high_risk_is_blocked(self):
        candidate = {
            "candidate_id": "candidate-1", "chunk_id": "chunk-1", "species": "鰻魚",
            "possible_category": "drug", "possible_categories": ["drug"],
            "risk_level": "high", "source_verification_status": "pending",
        }
        slots, _ = build_pilot_slots([candidate])
        high_slots = [row for row in slots if row["category"] == "drug"]
        self.assertTrue(high_slots)
        for row in high_slots:
            self.assertEqual(row["annotation_status"], "blocked")
            self.assertIsNone(row["gold_answer"])
            self.assertEqual(row["gold_chunks"], [])

    def test_unrepresented_conflicts_do_not_create_fake_slots(self):
        slots, summary = build_pilot_slots([])
        self.assertFalse(any(row["category"] in {"conflicting_sources", "insufficient_information", "ambiguous"} for row in slots))
        self.assertIn("conflicting_sources", summary["blocked_categories"])


if __name__ == "__main__":
    unittest.main()
