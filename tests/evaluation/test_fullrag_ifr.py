import unittest
from src.evaluation.edge.core19b import ifr

class IFRTest(unittest.TestCase):
    def test_retry_recovery_not_final_failure(self):
        rows=[dict(final_failed=False,retry_triggered=True),dict(final_failed=True,generation_failed=True),dict(final_failed=True,retrieval_failed=True)]
        r=ifr(rows);self.assertEqual(r['n_total'],3);self.assertAlmostEqual(r['final_IFR'],2/3)
        self.assertAlmostEqual(r['generation_IFR'],1/3);self.assertAlmostEqual(r['retrieval_IFR'],1/3)
    def test_no_execution_not_zero_IFR(self):self.assertIsNone(ifr([])['final_IFR'])
