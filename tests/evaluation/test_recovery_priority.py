import unittest

from src.evaluation.corpus_gaps import priority_score


class RecoveryPriorityTests(unittest.TestCase):
    def test_questions_facts_species_categories_risk_and_feasibility_affect_score(self):
        base = priority_score(affected_questions=1, affected_facts=1, species_count=1, category_count=1, high_risk=False, feasibility=0)
        high = priority_score(affected_questions=2, affected_facts=2, species_count=2, category_count=2, high_risk=True, feasibility=6)
        self.assertGreater(high, base)

    def test_feasibility_is_bounded(self):
        zero = priority_score(affected_questions=0, affected_facts=0, species_count=0, category_count=0, high_risk=False, feasibility=-4)
        maximum = priority_score(affected_questions=0, affected_facts=0, species_count=0, category_count=0, high_risk=False, feasibility=100)
        self.assertEqual(zero, 0)
        self.assertEqual(maximum, 6)


if __name__ == "__main__":
    unittest.main()
