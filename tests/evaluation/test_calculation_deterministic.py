import unittest
from src.evaluation.phase20_1r_protocol import calculation_unit_ready

class DeterministicCalculationTests(unittest.TestCase):
    def test_expected_answer_must_not_be_candidate_authored(self):
        row={"calculation_unit_id":"c1","species":"鰻魚","formula":"a*b","variables":{"a":"kg","b":"g/kg"},"units":"g","valid_range":"positive","expected_operation":"multiply","rounding_rule":"nearest g","allowed_tolerance":1,"source_doc":"manual","page":2,"checksum":"a"*64,"deterministic_expected_answer_source":"formula","candidate_llm_authored_expected_answer":False}
        self.assertTrue(calculation_unit_ready(row))
        row["candidate_llm_authored_expected_answer"]=True
        self.assertFalse(calculation_unit_ready(row))
