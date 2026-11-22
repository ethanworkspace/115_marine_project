import hashlib
import unittest

from src.evaluation.generation.contexts import build_oracle_contexts


class OracleContextTests(unittest.TestCase):
    def test_uses_snapshot_and_checks_checksum(self):
        text = "oracle evidence"
        checksum = hashlib.sha256(text.encode()).hexdigest()
        question = {"question_id": "q", "required_chunks": ["c"], "evidence_snapshot": [{"chunk_id": "c", "document_id": "d", "page": 1, "content_checksum": checksum, "text_snapshot": text}]}
        corpus = {"c": {"chunk_id": "c", "document_id": "d", "page_start": 1, "page_end": 1, "text": text, "content_checksum": checksum}}
        self.assertEqual(build_oracle_contexts(question, corpus)[0]["chunk_id"], "c")
        question["evidence_snapshot"][0]["text_snapshot"] = "changed"
        with self.assertRaises(ValueError):
            build_oracle_contexts(question, corpus)


if __name__ == "__main__":
    unittest.main()
