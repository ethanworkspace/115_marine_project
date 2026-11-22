import unittest

from src.evaluation.phase20_1_protocol import candidate_identity_ready


class WrongM3RejectedTests(unittest.TestCase):
    def test_qwen3_historical_artifact_cannot_satisfy_llama_candidate(self):
        old = {
            "identity_verified": False, "digest": "a" * 64,
            "artifact_sha256": "b" * 64, "artifact_checksum_match": True,
            "lineage_verified": False, "architecture": "qwen3",
            "parameter_count": 8_200_000_000, "quantization": "Q4_K_M",
            "artifact_size_bytes": 1, "context_length": 131072,
            "tokenizer_identity": "qwen3", "source_url": "https://ollama.com/library/deepseek-r1",
        }
        self.assertFalse(candidate_identity_ready(old))


if __name__ == "__main__":
    unittest.main()
