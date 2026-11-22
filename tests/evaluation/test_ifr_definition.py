import unittest
from tests.evaluation.edge19a_fixtures import row
from src.evaluation.edge.analysis19a import ifr
class IfrTest(unittest.TestCase):
    def test_retry_recovery_is_not_final_failure(self):
        r=ifr([row(first_pass_schema_valid=False,retry_triggered=True,retry_success=True),row(status='generation_error',final_schema_valid=False)],2)
        self.assertEqual(r['final_IFR'],.5);self.assertEqual(r['retry_success'],1)
    def test_empty_is_not_zero_failure(self):self.assertIsNone(ifr([],180)['final_IFR'])
