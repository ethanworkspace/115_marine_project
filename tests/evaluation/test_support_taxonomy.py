import unittest
from src.evaluation.human_support.core import attribution, validate_submission
from tests.evaluation.human_support_fixtures import record,submission


class TaxonomyTest(unittest.TestCase):
    def test_fully_and_partially_supported(self):
        self.assertEqual(attribution('fully_supported','not_applicable'),'correct_citation_support')
        self.assertEqual(attribution('partially_supported','cannot_determine'),'partial_citation_support')

    def test_indeterminate_alternative_does_not_establish_context_failure(self):
        self.assertEqual(attribution('not_supported','partially_supported_elsewhere'),'cannot_determine')

    def test_not_applicable_requires_full_support(self):
        x=submission(support='not_supported');x['elsewhere_support']='not_applicable'
        with self.assertRaises(ValueError):validate_submission(record(),'K_test',x)

    def test_missing_frozen_pair_cannot_be_dropped(self):
        x=submission();x['citations']=[]
        with self.assertRaises(ValueError):validate_submission(record(),'K_test',x)
