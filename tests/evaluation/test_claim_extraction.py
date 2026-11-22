import unittest
from src.evaluation.validity.core import extract_claims,verify_claim,structural_only
from tests.evaluation.phase18_fixtures import row


class ClaimsTest(unittest.TestCase):
    def test_exact_source_spans(self):
        r=row(answer='水質要檢查。\n濃度是 5.5 mg/L；每日觀察。')
        c=extract_claims(r)
        self.assertEqual(len(c),3)
        self.assertTrue(all(verify_claim(k,r['answer']) for k in c))
        self.assertIn('5.5',c[1]['claim_text'])

    def test_no_knowledge_added(self):
        r=row(answer='魚隻需觀察。')
        self.assertEqual(extract_claims(r)[0]['claim_text'],r['answer'])

    def test_heading_only_retained_as_zero_claims(self):
        self.assertEqual(extract_claims(row(answer='管理項目如下：')),[])

    def test_stable_claim_id(self):
        self.assertEqual(extract_claims(row()),extract_claims(row()))

    def test_structural_number_but_numeric_answer_kept(self):
        self.assertEqual(structural_only({'claim_text':'1.'}),'list_number_only')
        self.assertIsNone(structural_only({'claim_text':'1.35'}))
