import unittest

from src.evaluation.phase10_recovery import build_missing_source_registry


class MissingSourceRegistryTests(unittest.TestCase):
    def test_does_not_invent_missing_url_or_promote_authority(self):
        rows = build_missing_source_registry([{
            "source_alias_id": "a", "excel_source_id": "S1", "source_title": "title",
            "source_url": None, "affected_questions": ["q"], "affected_facts": ["f"],
            "species": ["鰻魚"], "categories": ["fact"], "identity_status": "unresolved",
            "authority_status": "unknown",
        }])
        self.assertIsNone(rows[0]["source_url"])
        self.assertEqual(rows[0]["acquisition_status"], "pending")
        self.assertEqual(rows[0]["authority_status"], "unknown")
        self.assertEqual(rows[0]["legal_status"], "unknown")

    def test_acquired_alias_keeps_real_status_fields(self):
        rows = build_missing_source_registry([{"source_alias_id": "b", "source_url": "https://law.example/1"}], acquisitions={
            "b": {"organization": "政府機關", "source_tier": 1, "identity_status": "verified",
                  "authority_status": "verified_official", "legal_status": "current",
                  "acquisition_status": "acquired"}
        })
        self.assertEqual(rows[0]["source_tier"], 1)
        self.assertEqual(rows[0]["legal_status"], "current")


if __name__ == "__main__":
    unittest.main()
