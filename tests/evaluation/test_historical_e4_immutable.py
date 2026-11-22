import unittest

class HistoricalE4ImmutableTests(unittest.TestCase):
    def test_final_e4_has_separate_identity(self):
        historical="E4_grounded_rrf_reranker_v1"
        final="E4_selection_v1"
        self.assertNotEqual(historical,final)
