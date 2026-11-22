import unittest
from collections import Counter

from src.evaluation.phase20_protocol import SPECIES, split_questions


class SelectionHoldoutTests(unittest.TestCase):
    def test_seeded_split_is_120_60_and_species_stratified(self):
        rows = [{"question_id": f"{sp}-{i}", "species": sp,
                 "category": "Fact", "style": ("Direct", "Paraphrase", "Contextual")[i % 3]}
                for sp in SPECIES for i in range(30)]
        selection, holdout = split_questions(rows)
        self.assertEqual((len(selection), len(holdout)), (120, 60))
        self.assertEqual(Counter(q["species"] for q in selection), {s: 20 for s in SPECIES})
        self.assertEqual(Counter(q["species"] for q in holdout), {s: 10 for s in SPECIES})


if __name__ == "__main__":
    unittest.main()
