import unittest

from src.evaluation.phase20_protocol import SPECIES


class SixSpeciesBalanceTests(unittest.TestCase):
    def test_all_six_species_are_fixed(self):
        self.assertEqual(len(SPECIES), 6)
        self.assertEqual(set(SPECIES), {"虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"})


if __name__ == "__main__":
    unittest.main()
