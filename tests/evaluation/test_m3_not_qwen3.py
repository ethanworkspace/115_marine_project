import unittest
from src.evaluation.phase20_1r_protocol import m3_identity_ready

class M3NotQwen3Tests(unittest.TestCase):
    def test_qwen3_lineage_is_rejected(self):
        self.assertFalse(m3_identity_ready({"candidate_model":"deepseek-ai/DeepSeek-R1-Distill-Llama-8B", "base_model_source":"deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"}))
