import json
from pathlib import Path
import unittest


class JudgeCalibrationSetTests(unittest.TestCase):
    def test_fixed_30_output_set_is_blinded_and_not_phase20_holdout(self):
        base = Path("reports/evaluation/final_model_selection/phase20_1")
        manifest = json.loads((base / "judge_calibration_manifest.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (base / "judge_calibration_set.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(30, len(rows))
        self.assertEqual(15, manifest["oracle_outputs"])
        self.assertEqual(15, manifest["e4_top5_outputs"])
        self.assertTrue(all(row["generator_identity_withheld"] for row in rows))
        self.assertTrue(all("generator" not in row and "model" not in row for row in rows))
        self.assertIn("no Phase 20 Selection or Holdout", manifest["sampling_rule"])


if __name__ == "__main__":
    unittest.main()
