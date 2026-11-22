import json
import unittest
from pathlib import Path


class GoldSchemaTests(unittest.TestCase):
    def test_schema_has_statuses_and_categories(self):
        schema = json.loads(Path("schemas/gold_question.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["annotation_status"]["enum"], ["draft", "annotated", "reviewed", "blocked", "locked"])
        self.assertIn("withdrawal_period", schema["properties"]["category"]["enum"])
        self.assertEqual(schema["properties"]["source_verification_status"]["enum"], ["not_required", "pending", "verified", "failed"])


if __name__ == "__main__":
    unittest.main()
