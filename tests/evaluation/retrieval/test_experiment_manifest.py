import unittest

from src.evaluation.retrieval.experiment import validate_experiment_manifest


class ExperimentManifestTests(unittest.TestCase):
    def test_valid_manifest(self):
        manifest = {key: None for key in ("evaluation_corpus_sha256", "gold_dataset_sha256", "retriever_type", "retriever_config", "chunking_version", "embedding_model", "embedding_dimension", "top_k", "git_commit", "notes")}
        manifest.update({"experiment_id": "synthetic-test", "timestamp": "2026-10-03T00:00:00Z"})
        self.assertEqual(validate_experiment_manifest(manifest), [])

    def test_missing_fields_and_invalid_hash_fail(self):
        self.assertTrue(validate_experiment_manifest({"experiment_id": "bad", "evaluation_corpus_sha256": "xx"}))
