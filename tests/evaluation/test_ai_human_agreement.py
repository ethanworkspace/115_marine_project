import unittest
from src.evaluation.human_support.core import ai_human_agreement, categorical_agreement


class AgreementTest(unittest.TestCase):
    def test_no_pairs_unavailable(self):
        r=ai_human_agreement({},[])
        self.assertEqual(r['n_paired'],0);self.assertIsNone(r['raw_agreement'])
        self.assertIsNone(r['cohen_kappa'])

    def test_ai_false_support_candidates_not_ground_truth(self):
        ai={'P':{'effective_verdict':'entailed'}}
        h=[{'pair_id':'P','new_value':{'support':'not_supported'}}]
        r=ai_human_agreement(ai,h)
        self.assertEqual(r['ai_false_support_candidate'],1)
        self.assertTrue(r['ai_is_not_ground_truth'])

    def test_full_confusion_matrix_and_kappa(self):
        a=['fully_supported','not_supported'];b=['not_supported','fully_supported']
        r=categorical_agreement(a,b)
        self.assertEqual(r['cohen_kappa'],-1)
        self.assertEqual(r['percent_agreement'],0)
        self.assertEqual(r['confusion_matrix']['fully_supported']['not_supported'],1)

    def test_constant_labels_kappa_unavailable(self):
        r=categorical_agreement(['fully_supported'],['fully_supported'])
        self.assertEqual(r['raw_agreement'],1);self.assertIsNone(r['cohen_kappa'])

    def test_missing_pair_not_silently_dropped(self):
        with self.assertRaises(ValueError):ai_human_agreement({},[{'pair_id':'P','new_value':{'support':'not_supported'}}])
