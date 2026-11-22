import unittest

from src.evaluation.corpus_gaps import mapping_counts, priority_score, stable_alias_id


class GapRegistryTests(unittest.TestCase):
    def test_alias_id_is_stable_and_key_scoped(self):
        self.assertEqual(stable_alias_id("book.xlsx::S01"), stable_alias_id("book.xlsx::S01"))
        self.assertNotEqual(stable_alias_id("book.xlsx::S01"), stable_alias_id("book.xlsx::S02"))

    def test_mapping_counts_do_not_rename_silver_statuses(self):
        rows = [{"evidence_mapping_status": "medium_confidence"}, {"evidence_mapping_status": "unmapped"}]
        self.assertEqual(mapping_counts(rows)["medium_confidence"], 1)
        self.assertEqual(mapping_counts(rows)["unmapped"], 1)

    def test_gap_priority_is_deterministic(self):
        args = dict(affected_questions=3, affected_facts=2, species_count=2, category_count=1, high_risk=True, feasibility=5)
        self.assertEqual(priority_score(**args), priority_score(**args))


if __name__ == "__main__":
    unittest.main()
