import unittest
from src.evaluation.validity.core import validate_entailment,claim_verdict


class EntailmentTest(unittest.TestCase):
    def test_allowed_labels(self):
        p={'judgments':[{'context_id':'C1','verdict':'entailed','supporting_quote':'text','reason':'ok'}]}
        self.assertEqual(validate_entailment(p,['C1']),p)

    def test_no_fake_binary_label(self):
        with self.assertRaises(Exception):validate_entailment({'judgments':[{'context_id':'C1',
            'verdict':'correct','supporting_quote':'','reason':''}]},['C1'])

    def test_duplicate_judgment_rejected(self):
        j={'context_id':'C1','verdict':'cannot_determine','supporting_quote':'','reason':''}
        with self.assertRaises(Exception):validate_entailment({'judgments':[j,j]},['C1','C2'])

    def test_unknown_not_counted_unsupported(self):
        self.assertEqual(claim_verdict([{'effective_verdict':'not_entailed'},
            {'effective_verdict':'cannot_determine'}]),'cannot_determine')
        self.assertEqual(claim_verdict([]),'citation_missing')
