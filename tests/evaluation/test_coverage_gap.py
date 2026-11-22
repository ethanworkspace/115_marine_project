import unittest

from src.evaluation.development import build_coverage_report


class CoverageGapTests(unittest.TestCase):
    def test_metadata_unknown_and_no_candidate_are_distinguished(self):
        candidates = [{"chunk_id": "c1", "species": None, "possible_categories": ["fact"],
                       "benchmark_eligible": True, "risk_level": "normal", "species_basis": None}]
        report = build_coverage_report([], candidates, [])
        by_pair = {(row["species"], row["category"]): row for row in report["species_categories"]}
        self.assertEqual(by_pair[("吳郭魚", "fact")]["status"], "metadata_unknown")
        self.assertEqual(by_pair[("吳郭魚", "water_quality")]["status"], "no_candidate")

    def test_unverified_high_risk_coverage_is_source_blocked(self):
        candidates = [{"chunk_id": "c1", "species": "吳郭魚", "possible_categories": ["water_quality"],
                       "benchmark_eligible": False, "risk_level": "high", "source_verification_status": "pending"}]
        report = build_coverage_report([], candidates, [])
        row = next(item for item in report["species_categories"] if item["species"] == "吳郭魚" and item["category"] == "water_quality")
        self.assertEqual(row["status"], "source_blocked")
        self.assertEqual(row["source_blocked_high_risk_count"], 1)


if __name__ == "__main__":
    unittest.main()
