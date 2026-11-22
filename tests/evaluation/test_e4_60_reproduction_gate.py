import unittest
from src.evaluation.edge.core19b import reproduction_gate
class E4RecoveryTest(unittest.TestCase):
    def test_requires_sixty_ordered_Top5_matches(self):
        rows={str(q):list('abcde') for q in range(60)}
        self.assertTrue(reproduction_gate(rows,rows)['retrieval_reproducibility_pass'])
        actual={**rows,'0':list('bacde')};self.assertFalse(reproduction_gate(rows,actual)['retrieval_reproducibility_pass'])
    def test_59_matches_not_ready(self):
        rows={str(q):list('abcde') for q in range(59)}
        self.assertFalse(reproduction_gate(rows,rows)['retrieval_reproducibility_pass'])
