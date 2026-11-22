import unittest
from collections import Counter
from src.evaluation.validity.core import stratified_outputs,identity
from tests.evaluation.phase18_fixtures import rows


class JudgeSampleTest(unittest.TestCase):
    def test_balanced_96_deterministic(self):
        a=stratified_outputs(rows());b=stratified_outputs(list(reversed(rows())))
        self.assertEqual([identity(x) for x in a],[identity(x) for x in b])
        self.assertEqual(len(a),96)
        self.assertEqual(set(Counter((x['generator'],x['condition']) for x in a).values()),{12})

    def test_audit_48(self):
        r=stratified_outputs(rows(),audit=True)
        self.assertEqual(len(r),48)
        self.assertTrue(all(x['condition']=='e4_top5' for x in r))

    def test_no_replacement_of_answer_status(self):
        r=rows()
        for x in r:x['status']='generation_error'
        with self.assertRaises(ValueError):stratified_outputs(r)
