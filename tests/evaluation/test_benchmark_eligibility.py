import unittest

from tests.evaluation.helpers import build, make_chunk, make_doc


class BenchmarkEligibilityTests(unittest.TestCase):
    def test_high_risk_unverified_is_ineligible(self):
        row = build([make_chunk("reg", strategy="regulation")], [make_doc(title="養殖規則")])[0]
        self.assertEqual(row["risk_level"], "high")
        self.assertFalse(row["benchmark_eligible"])

    def test_unknown_legal_status_is_not_promoted_to_current(self):
        row = build([make_chunk("reg", strategy="regulation", verified=True, legal="unknown")], [make_doc()])[0]
        self.assertEqual(row["legal_status"], "unknown")
        self.assertNotEqual(row["legal_status"], "current")
        self.assertFalse(row["benchmark_eligible"])

    def test_normal_risk_pending_source_is_experimental_eligible(self):
        row = build([make_chunk("normal")], [make_doc()])[0]
        self.assertTrue(row["benchmark_eligible"])
        self.assertEqual(row["source_verification_status"], "pending")
        self.assertIn("experimental", row["verification_requirement"])


if __name__ == "__main__":
    unittest.main()
