import unittest

from src.evaluation.grounded_baselines import OllamaEmbeddingRuntime


class DensePreflightTests(unittest.TestCase):
    def test_requires_bge_tag_and_checks_runtime_dimension(self):
        runtime = OllamaEmbeddingRuntime()
        calls = []

        def request(endpoint, payload=None):
            calls.append(endpoint)
            if endpoint == "api/version": return {"version": "test"}
            if endpoint == "api/tags": return {"models": [{"name": "bge-m3:latest", "digest": "abc", "details": {"embedding_length": 3, "family": "bert"}}]}
            if endpoint == "api/show": return {"model_info": {}}
            if endpoint == "api/ps": return {"models": [{"name": "bge-m3:latest", "size_vram": 4}]}
            raise AssertionError(endpoint)

        runtime._request = request
        runtime.embed_texts = lambda texts, batch_size=32: [[1.0, 0.0, 0.0] for _ in texts]
        metadata = runtime.preflight()
        self.assertEqual(metadata["embedding_dimension"], 3)
        self.assertEqual(metadata["model_digest"], "abc")
        self.assertTrue(metadata["embedding_repeat_probe_exact"])
        self.assertEqual(metadata["runtime_size_vram_bytes"], 4)
        self.assertIn("api/show", calls)

    def test_does_not_choose_fallback_model(self):
        runtime = OllamaEmbeddingRuntime()
        runtime._request = lambda endpoint, payload=None: {"version": "test"} if endpoint == "api/version" else {"models": []}
        with self.assertRaisesRegex(RuntimeError, "Required BGE-M3 model tag unavailable"):
            runtime.preflight()


if __name__ == "__main__":
    unittest.main()
