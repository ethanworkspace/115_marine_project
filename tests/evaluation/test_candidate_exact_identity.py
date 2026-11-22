import unittest
import json
from pathlib import Path

from src.evaluation.phase20_1_protocol import candidate_identity_ready


class CandidateExactIdentityTests(unittest.TestCase):
    def test_requires_full_local_artifact_and_lineage_checks(self):
        row = {
            "identity_verified": True, "digest": "a" * 64,
            "artifact_sha256": "b" * 64, "artifact_checksum_match": True,
            "lineage_verified": True, "architecture": "qwen2",
            "parameter_count": 7_600_000_000, "quantization": "Q4_K_M",
            "artifact_size_bytes": 100, "context_length": 8192,
            "tokenizer_identity": "tokenizer-a", "source_url": "https://example.org/model",
        }
        self.assertTrue(candidate_identity_ready(row))
        row["artifact_checksum_match"] = False
        self.assertFalse(candidate_identity_ready(row))

    def test_rechecked_m1_m2_manifests_are_frozen(self):
        base = Path("reports/evaluation/final_model_selection/phase20_1")
        for model_id, expected in (("M1", "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"), ("M2", "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364")):
            row = json.loads((base / f"{model_id}_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(expected, row["digest"])
            self.assertTrue(row["artifact_checksum_match"])
            self.assertTrue(row["identity_verified"])


if __name__ == "__main__":
    unittest.main()
