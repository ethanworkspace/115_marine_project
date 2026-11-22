from __future__ import annotations

import importlib.util
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerModelLoadTests(unittest.TestCase):
    def test_requested_local_model_loads(self) -> None:
        runtime = get_runtime()
        self.assertEqual(runtime.load_info.model_id, "BAAI/bge-reranker-v2-m3")
        self.assertEqual(runtime.load_info.model_class, "XLMRobertaForSequenceClassification")
        self.assertTrue(runtime.load_info.tokenizer_is_fast)
        self.assertGreater(runtime.load_info.parameter_count, 0)


if __name__ == "__main__":
    unittest.main()
