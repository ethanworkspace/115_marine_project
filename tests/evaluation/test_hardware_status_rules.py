import unittest
from tests.evaluation.edge19a_fixtures import complete,cold,row
from src.evaluation.edge.analysis19a import status
class StatusTest(unittest.TestCase):
    def test_full_no_failure(self):self.assertEqual(status(complete(),cold(),[]),'deployable_on_device')
    def test_retry_is_limitation(self):
        rs=complete();rs[0]['retry_triggered']=True;self.assertEqual(status(rs,cold(),[]),'deployable_with_limitations')
    def test_oom_is_not_feasible(self):self.assertEqual(status([row(technical_failures=[{'category':'OOM'}])],[],[]),'not_feasible')
    def test_interruption_is_incomplete(self):self.assertEqual(status([],[],[],external_interrupt=True),'benchmark_incomplete')
