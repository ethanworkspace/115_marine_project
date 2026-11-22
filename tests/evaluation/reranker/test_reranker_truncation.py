from __future__ import annotations

import importlib.util
import unittest

try:
    from .runtime_test_support import get_runtime
except ImportError:
    from runtime_test_support import get_runtime


@unittest.skipUnless(importlib.util.find_spec("torch"), "reranker runtime is installed only in .venv-reranker")
class RerankerTruncationTests(unittest.TestCase):
    def test_long_pair_is_truncated_to_configured_limit(self) -> None:
        runtime = get_runtime()
        query = "養殖池水質管理 " * 700
        passage = "溶氧與氨氮應定期檢查 " * 700
        original_length = runtime.untruncated_token_lengths(query, [passage])[0]
        self.assertGreater(original_length, runtime.max_length)
        values = runtime.score_pairs(query, [passage])
        self.assertEqual(len(values), 1)
        encoded = runtime.tokenizer(
            [query], [passage], padding="longest", truncation="longest_first",
            max_length=runtime.max_length, return_tensors="pt",
        )
        self.assertLessEqual(int(encoded["attention_mask"].sum().item()), runtime.max_length)


if __name__ == "__main__":
    unittest.main()
