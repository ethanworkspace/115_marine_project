import unittest
from src.evaluation.phase20_1r_protocol import m3_identity_ready

class M3GGUFIdentityTests(unittest.TestCase):
    def test_quantization_filename_and_hash_are_required(self):
        row = dict(candidate_model="deepseek-ai/DeepSeek-R1-Distill-Llama-8B", base_model_source="deepseek-ai/DeepSeek-R1-Distill-Llama-8B", source_repository="bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF", file_name="DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf", quantization="Q4_K_M", architecture="llama", artifact_size_bytes=10, artifact_sha256="a"*64, ollama_digest="b"*64, runtime_smoke_pass=True, context_8192_smoke_pass=True)
        row["artifact_sha256"] = "unknown"
        self.assertFalse(m3_identity_ready(row))
