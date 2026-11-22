import tempfile
import unittest
from pathlib import Path

from src.evaluation.grounded_baselines import build_dense_index, load_dense_index
from tests.evaluation.grounded_baseline_fixtures import corpus_rows, question


class FakeRuntime:
    dimension = 3

    def embed_texts(self, texts, *, batch_size=32):
        return [[float(len(text) % 3 + 1), 1.0, 1.0] for text in texts]


class DenseIndexManifestTests(unittest.TestCase):
    def test_index_manifest_records_frozen_corpus_and_model(self):
        rows = corpus_rows()
        frozen = {"corpus": rows, "questions": [question()],
                  "hashes": {"evaluation_corpus_v2": "corpus-sha"},
                  "corpus_chunk_ids_sha256": "ids-sha",
                  "corpus_profile": {"document_count": 2, "page_count": 2}}
        metadata = {"model_tag": "bge-m3:latest", "embedding_dimension": 3, "runtime_version": "test"}
        with tempfile.TemporaryDirectory() as temp:
            retriever, manifest = build_dense_index(Path(temp), frozen, FakeRuntime(), metadata, "commit", "time")
            self.assertEqual(manifest["index_id"], "E2_grounded_bge_m3_v1")
            self.assertEqual(manifest["retrieval_chunk_count"], 4)
            self.assertEqual(manifest["embedding_dimension"], 3)
            self.assertFalse(manifest["uses_production_vectors"])
            self.assertEqual(len(retriever.retrieve("如何管理水質？", top_k=2)), 2)
            self.assertTrue((Path(temp) / "data/evaluation/indexes/E2_grounded_bge_m3_v1/vectors.f32").is_file())
            loaded, loaded_manifest = load_dense_index(Path(temp), frozen)
            self.assertEqual(loaded_manifest["vectors_sha256"], manifest["vectors_sha256"])
            self.assertEqual(loaded.vectors, retriever.vectors)
            self.assertEqual(loaded.retrieve("如何管理水質？", top_k=2), retriever.retrieve("如何管理水質？", top_k=2))


if __name__ == "__main__":
    unittest.main()
