import unittest
from copy import deepcopy
from .phase17_fixtures import row
from src.evaluation.generation_models.core import assert_same_inputs

class SameContextTests(unittest.TestCase):
    def test_same_context(self): assert_same_inputs([row()],[row()])
    def test_changed_page(self):
        b=row(); b['context_provenance'][0]['page']=2
        with self.assertRaises(ValueError): assert_same_inputs([row()],[b])
    def test_changed_evidence(self):
        b=row(); b['contexts']=['changed']
        with self.assertRaises(ValueError): assert_same_inputs([row()],[b])
