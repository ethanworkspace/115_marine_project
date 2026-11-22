import json
from pathlib import Path
import unittest


class GemmaLineageTests(unittest.TestCase):
    def test_local_artifact_lineage_matches_official_instruct_tag(self):
        path = Path("reports/evaluation/final_model_selection/phase20_1/M4_manifest.json")
        row = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(row["identity_verified"])
        self.assertTrue(row["lineage_verified"])
        self.assertEqual("google/gemma-2-9b-it", row["base_model"])
        self.assertEqual("Q4_0", row["quantization"])
        self.assertTrue(row["digest"].startswith(row["official_tag_digest_prefix"]))
        self.assertEqual("https://huggingface.co/google/gemma-2-9b-it", row["source_url"])


if __name__ == "__main__":
    unittest.main()
