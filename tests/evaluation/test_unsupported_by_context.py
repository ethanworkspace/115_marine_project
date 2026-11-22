import unittest
from src.evaluation.human_support.core import attribution, support_summary


class UnsupportedTest(unittest.TestCase):
    def test_absence_only_not_world_falsity(self):
        self.assertEqual(attribution('not_supported','not_supported_anywhere'),'unsupported_by_provided_context')
        self.assertIn('no assertion of real-world falsity',support_summary([],[])['unsupported_definition'])

    def test_uncertainty_not_automatically_unsupported(self):
        self.assertEqual(attribution('cannot_determine','not_supported_anywhere'),'cannot_determine')
