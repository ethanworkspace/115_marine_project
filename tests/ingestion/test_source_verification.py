import unittest

from src.ingestion.phase6 import classify_source_priority


class SourceVerificationTests(unittest.TestCase):
    def test_unknown_legal_status_is_not_promoted_to_current(self):
        document = {
            "title": "一般參考資料", "source_id": "unverified", "source_url": None,
            "legal_status": "unknown", "source_tier": None,
        }
        status_before = document["legal_status"]
        priority, _ = classify_source_priority(document)
        self.assertEqual(document["legal_status"], status_before)
        self.assertEqual(document["legal_status"], "unknown")
        self.assertIn(priority, {1, 2, 3, 4})

    def test_medication_topic_is_ranked_for_early_verification(self):
        priority, _ = classify_source_priority({"title": "動物用藥與停藥期說明"})
        self.assertEqual(priority, 1)


if __name__ == "__main__":
    unittest.main()
