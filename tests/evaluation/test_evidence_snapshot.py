import unittest

from src.evaluation.annotation import make_evidence_snapshot, sha256_text
from tests.evaluation.helpers import build, make_chunk, make_doc


class EvidenceSnapshotTests(unittest.TestCase):
    def test_snapshot_keeps_source_text_and_integrity_hash(self):
        corpus = build([make_chunk("chunk-a", text="fish source text")], [make_doc()])
        snapshot = make_evidence_snapshot({row["chunk_id"]: row for row in corpus}, ["chunk-a"])[0]
        self.assertEqual(snapshot["document_id"], "doc-a")
        self.assertEqual(snapshot["page"], 1)
        self.assertEqual(snapshot["text_snapshot"], "fish source text")
        self.assertEqual(snapshot["snapshot_sha256"], sha256_text("fish source text"))

    def test_excluded_or_missing_chunks_cannot_be_snapshotted(self):
        corpus = build([make_chunk("review", status="review")], [make_doc()])
        by_id = {row["chunk_id"]: row for row in corpus}
        with self.assertRaises(ValueError):
            make_evidence_snapshot(by_id, ["review"])
        with self.assertRaises(ValueError):
            make_evidence_snapshot(by_id, ["unknown"])


if __name__ == "__main__":
    unittest.main()
