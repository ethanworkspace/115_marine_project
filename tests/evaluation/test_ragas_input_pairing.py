import unittest
from src.evaluation.ragas_eval.core import pair_inputs
from .ragas_fixtures import export_pair


class RagasInputPairingTests(unittest.TestCase):
    def test_exact_pair(self):
        self.assertEqual(len(pair_inputs(export_pair(), expected_count=1)), 1)

    def test_duplicate_and_missing_condition_fail(self):
        r = export_pair()
        with self.assertRaises(ValueError):
            pair_inputs(r + [r[0]], 1)
        with self.assertRaises(ValueError):
            pair_inputs(r[:1], 1)

    def test_reference_difference_fails(self):
        r = export_pair()
        r[1]['reference_answer'] = 'different'
        with self.assertRaises(ValueError):
            pair_inputs(r, 1)
