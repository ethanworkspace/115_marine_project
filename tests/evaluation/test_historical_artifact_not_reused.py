import json
from pathlib import Path
import unittest


class HistoricalArtifactDispositionTests(unittest.TestCase):
    def test_old_deepseek_8b_is_historical_only(self):
        path = Path("reports/evaluation/final_model_selection/phase20_1/historical_artifact_mapping.json")
        old = json.loads(path.read_text(encoding="utf-8"))["old_deepseek_r1_8b"]
        self.assertFalse(old["candidate_M3"])
        self.assertNotEqual(old["architecture"], "llama")
        self.assertTrue(old["historical_artifact_only"])
        self.assertFalse(old["permitted_as_substitute"])


if __name__ == "__main__":
    unittest.main()
