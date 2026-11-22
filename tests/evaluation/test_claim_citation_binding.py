import unittest
from src.evaluation.validity.core import extract_claims
from tests.evaluation.phase18_fixtures import row


class BindingTest(unittest.TestCase):
    def test_inline(self):
        c=extract_claims(row(answer='水質需檢查 [C1]。'))[0]
        self.assertEqual(c['linked_citations'],['C1'])
        self.assertEqual(c['citation_binding'],'claim_inline')

    def test_answer_level_not_fake_claim_binding(self):
        c=extract_claims(row())[0]
        self.assertEqual(c['linked_citations'],[])
        self.assertEqual(c['answer_level_citations'],['C1'])
        self.assertEqual(c['citation_binding'],'answer_level_only')

    def test_no_citation(self):
        r=row();r['deterministic_generation']['citations']=[]
        self.assertEqual(extract_claims(r)[0]['audit_citation_set'],[])
