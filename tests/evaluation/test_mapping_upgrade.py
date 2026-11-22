import unittest

from src.evaluation.source_mapping import _status_for_question


class MappingUpgradeTests(unittest.TestCase):
    def test_all_high_facts_upgrade_question(self):
        status, complete = _status_for_question([{"mapping_status": "high_confidence", "mapped_chunks": [{"chunk_id": "c1"}]}])
        self.assertEqual(status, "high_confidence")
        self.assertTrue(complete)

    def test_partial_fact_mapping_stays_medium(self):
        status, complete = _status_for_question([
            {"mapping_status": "high_confidence", "mapped_chunks": [{"chunk_id": "c1"}]},
            {"mapping_status": "unmapped", "mapped_chunks": []},
        ])
        self.assertEqual(status, "medium_confidence")
        self.assertFalse(complete)


if __name__ == "__main__":
    unittest.main()
