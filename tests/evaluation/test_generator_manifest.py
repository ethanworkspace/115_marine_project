import unittest
from .phase17_fixtures import manifest
from src.evaluation.generation_models.core import validate_manifest

class GeneratorManifestTests(unittest.TestCase):
    def test_frozen_roster(self):
        validate_manifest(manifest())
    def test_missing_digest(self):
        m=manifest(); m['generators'][1]['digest']=None
        with self.assertRaises(ValueError): validate_manifest(m)
    def test_duplicate_roster(self):
        m=manifest(); m['generators'].append(m['generators'][0])
        with self.assertRaises(ValueError): validate_manifest(m)
