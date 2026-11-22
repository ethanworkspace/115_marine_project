import unittest
from src.evaluation.human_support.core import attribution, validate_submission
from tests.evaluation.human_support_fixtures import record,submission


class SelectionFailureTest(unittest.TestCase):
    def test_unsupported_citation_supported_elsewhere(self):
        self.assertEqual(attribution('not_supported','supported_elsewhere'),'citation_selection_failure')

    def test_alternative_support_requires_human_selected_context(self):
        x=submission(support='not_supported');x['elsewhere_support']='supported_elsewhere'
        with self.assertRaises(ValueError):validate_submission(record(),'K_test',x)
        x['elsewhere_context_ids']=['C2']
        validate_submission(record(),'K_test',x)

    def test_cited_chunk_not_counted_as_elsewhere(self):
        x=submission(support='not_supported');x['elsewhere_support']='supported_elsewhere';x['elsewhere_context_ids']=['C1']
        with self.assertRaises(ValueError):validate_submission(record(),'K_test',x)
