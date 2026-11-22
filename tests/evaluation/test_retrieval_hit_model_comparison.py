import unittest
from .phase17_fixtures import row
from src.evaluation.generation_models.core import scalar

class RetrievalHitComparisonTests(unittest.TestCase):
    def test_abstention_not_answered_judge_score(self):
        r=row(); r['status']='insufficient_evidence'; self.assertIsNone(scalar(r,'faithfulness'))
    def test_error_not_reference_score(self):
        r=row(); r['status']='generation_error'; self.assertIsNone(scalar(r,'silver_token_f1'))
    def test_failed_partial_citation_not_system_recall_success(self):
        r=row(); r['status']='generation_error'; self.assertEqual(scalar(r,'citation_recall'),0)
