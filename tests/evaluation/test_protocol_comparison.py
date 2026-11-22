import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation.generation.runner_v2 import _v1_v2_comparison


class ProtocolComparisonTests(unittest.TestCase):
    def test_comparison_labels_reference_similarity_as_secondary_silver(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("G0_grounded_oracle_generation_v1", "G1_grounded_e4_top5_generation_v1"):
                folder = root / "reports/evaluation/generation" / name
                folder.mkdir(parents=True)
                (folder / "overall.json").write_text(json.dumps({
                    "schema_valid_rate": 1, "answered_count": 1,
                    "silver_reference_similarity": {"f1_mean": .5},
                    "calculation_numeric_evaluation": None,
                }), encoding="utf-8")
                (folder / "experiment_manifest.json").write_text(json.dumps({
                    "raw_output_capture": {"attempts": 1, "captured": 1},
                }), encoding="utf-8")
            summary = {"strict_citation_validity_rate": .5, "recoverable_citation_validity_rate": .8,
                       "required_evidence_citation_recall": {}}
            audit = {"conditions": {"G0": summary, "G1": summary}}
            v2 = {"schema_valid_rate": 1, "strict_citation_validity_rate": .9,
                  "recoverable_citation_validity_rate": .9, "required_evidence_citation_recall": {},
                  "raw_output_preservation_rate": 1, "answered_count": 1,
                  "silver_reference_similarity": {"f1_mean": .51}, "calculation_numeric_evaluation": None}
            result = _v1_v2_comparison(root, audit, {"G0": v2, "G1": v2})
            self.assertIn("protocol stabilization", result["comparison_type"])
            self.assertFalse(result["causal_claim"])
            self.assertEqual(result["conditions"]["G0"]["v2"]["strict_citation_validity_rate"], .9)


if __name__ == "__main__":
    unittest.main()
