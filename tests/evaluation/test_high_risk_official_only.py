import unittest

from src.evaluation.phase20_1_protocol import high_risk_unit_verified


class HighRiskSourceTests(unittest.TestCase):
    def test_unverified_current_applicability_never_passes(self):
        unit = {
            "category": "Safe Medication / Law", "review_status": "ready",
            "source_type": "official", "source_status": "verified",
            "current_applicability_verified": False, "authority": "MOA",
            "document_title": "Rule", "page": 1, "date_version": "2026-01",
            "applicability": "unknown", "checksum": "a" * 64,
        }
        self.assertFalse(high_risk_unit_verified(unit))


if __name__ == "__main__":
    unittest.main()
