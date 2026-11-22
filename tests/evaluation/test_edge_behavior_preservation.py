import unittest
from src.evaluation.edge.core import behavior_preservation


class BehaviorTest(unittest.TestCase):
    def test_normalized_not_exact_string_requirement(self):
        a=dict(question_id='q',answer='Ａ B',status='answered',citations=['C1','C2'],schema_valid=True)
        b=dict(question_id='q',answer='a  b',status='answered',citations=['C2','C1'],schema_valid=True)
        r=behavior_preservation(a,b)
        self.assertEqual(r['normalized_answer_similarity'],1)
        self.assertTrue(r['citation_set_exact']);self.assertTrue(r['status_agreement'])

    def test_different_question_cannot_pair(self):
        with self.assertRaises(ValueError):behavior_preservation({'question_id':'a'},{'question_id':'b'})

    def test_schema_failure_kept_in_comparison(self):
        a=dict(question_id='q',answer='test',status='answered',citations=['C1'],schema_valid=True)
        b=dict(question_id='q',answer='',status='generation_error',citations=[],schema_valid=False)
        r=behavior_preservation(a,b)
        self.assertFalse(r['schema_agreement']);self.assertFalse(r['status_agreement'])
