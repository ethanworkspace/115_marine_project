import unittest
from src.evaluation.edge.core19b import compare_top5

class DriftTest(unittest.TestCase):
    def test_rank_change_is_drift(self):self.assertFalse(compare_top5(list('abcde'),list('bacde'))['match'])
    def test_no_silent_missing_candidate(self):self.assertFalse(compare_top5(list('abcde'),list('abcd'))['match'])
    def test_identical_top5(self):self.assertTrue(compare_top5(list('abcde'),list('abcde'))['match'])
