import unittest
from src.evaluation.edge.core19b import reproduction_gate

class ReproductionTest(unittest.TestCase):
    def refs(self):return {str(q):['a','b','c','d','e'] for q in range(60)}
    def test_requires_sixty_identical_ordered_lists(self):
        self.assertTrue(reproduction_gate(self.refs(),self.refs())['retrieval_reproducibility_pass'])
    def test_one_order_mismatch_stops(self):
        actual=self.refs();actual['2']=['b','a','c','d','e']
        self.assertFalse(reproduction_gate(self.refs(),actual)['retrieval_reproducibility_pass'])
    def test_missing_query_stops(self):
        actual=self.refs();actual.pop('2')
        self.assertFalse(reproduction_gate(self.refs(),actual)['retrieval_reproducibility_pass'])
