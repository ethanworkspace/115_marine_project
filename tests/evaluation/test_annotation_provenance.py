import json
import unittest
from pathlib import Path


class AnnotationProvenanceTests(unittest.TestCase):
    def test_gold_schema_requires_corpus_identity_and_verification_flags(self):
        schema = json.loads(Path("schemas/gold_question.schema.json").read_text(encoding="utf-8"))
        required = set(schema["required"])
        self.assertTrue({"split", "created_at", "annotation_version", "evaluation_corpus_version",
                         "evaluation_corpus_sha256", "question_verified", "evidence_verified",
                         "gold_evidence_snapshot"}.issubset(required))

    def test_dataset_slots_bind_the_evaluation_corpus(self):
        manifest = json.loads(Path("data/evaluation/corpus_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["evaluation_corpus_sha256"]), 64)
        records = [json.loads(line) for line in Path("data/gold/development/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(records)
        for row in records:
            self.assertEqual(row["split"], "development")
            self.assertEqual(row["evaluation_corpus_sha256"], manifest["evaluation_corpus_sha256"])
            self.assertEqual(row["evaluation_corpus_version"], "evaluation-corpus-v1")


if __name__ == "__main__":
    unittest.main()
