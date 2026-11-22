import unittest

from src.evaluation.phase20_1_protocol import evidence_unit_errors


class EvidenceUnitSchemaTests(unittest.TestCase):
    def test_ready_unit_requires_provenance_and_checksum(self):
        unit = {
            "evidence_unit_id": "eu1", "species": "吳郭魚", "category": "Fact",
            "fact_or_rule": "A fact", "chunk_id": "c1", "document_id": "d1", "page": 1,
            "source_title": "Manual", "source_type": "official", "source_status": "verified",
            "date_version": "2026-01", "checksum": "f" * 64, "risk_level": "normal",
            "review_status": "ready", "notes": "checked",
        }
        self.assertEqual([], evidence_unit_errors(unit))
        unit["checksum"] = "bad"
        self.assertIn("ready_unit_invalid_checksum", evidence_unit_errors(unit))


if __name__ == "__main__":
    unittest.main()
