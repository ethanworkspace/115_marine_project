import unittest

from src.evaluation.phase20_1_protocol import CATEGORIES, SPECIES, empty_evidence_matrix


class EvidenceMatrixTests(unittest.TestCase):
    def test_full_species_category_cross_product(self):
        rows = empty_evidence_matrix([])
        self.assertEqual(36, len(rows))
        self.assertEqual(36, len({(r["species"], r["category"]) for r in rows}))
        self.assertEqual(set(SPECIES), {r["species"] for r in rows})
        self.assertEqual(set(CATEGORIES), {r["category"] for r in rows})

    def test_screening_chunks_do_not_become_ready_units(self):
        rows = empty_evidence_matrix([{
            "species": "吳郭魚", "category": "Calculation",
            "screening_candidate_chunk_count": 16, "status": "review_required",
        }])
        row = next(r for r in rows if r["species"] == "吳郭魚" and r["category"] == "Calculation")
        self.assertEqual(16, row["screening_candidate_chunk_count"])
        self.assertEqual(0, row["ready_unit_count"])
        self.assertFalse(row["question_capacity_confirmed"])


if __name__ == "__main__":
    unittest.main()
