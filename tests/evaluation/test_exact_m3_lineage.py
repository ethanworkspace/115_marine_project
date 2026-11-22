import unittest
from src.evaluation.phase20_1r_protocol import m3_identity_ready

class ExactM3LineageTests(unittest.TestCase):
    def test_requires_the_requested_official_base_lineage(self):
        row = dict(candidate_model="deepseek-ai/DeepSeek-R1-Distill-Llama-8B", base_model_source="deepseek-ai/DeepSeek-R1-Distill-Llama-8B", source_repository="bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF", file_name="DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf", quantization="Q4_K_M", architecture="llama", artifact_size_bytes=1, artifact_sha256="a"*64, ollama_digest="b"*64, runtime_smoke_pass=True, context_8192_smoke_pass=True)
        self.assertTrue(m3_identity_ready(row))
        row["base_model_source"] = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
        self.assertFalse(m3_identity_ready(row))
