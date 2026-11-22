import unittest

from src.evaluation.phase10_recovery import validate_source_provenance


class RecoveryProvenanceTests(unittest.TestCase):
    def test_chunk_resolves_to_document_checksum_and_page(self):
        chunk = {"chunk_id": "c", "document_id": "d", "page_start": 2, "page_end": 3,
                 "source_span_ids": ["s"]}
        span = {"source_span_id": "s", "document_id": "d", "file_checksum": "x" * 64, "page_number": 2}
        manifest = {"document_id": "d", "checksum": "x" * 64}
        validate_source_provenance([chunk], [span], [manifest])

    def test_wrong_checksum_fails(self):
        chunk = {"chunk_id": "c", "document_id": "d", "page_start": 1, "page_end": 1,
                 "source_span_ids": ["s"]}
        span = {"source_span_id": "s", "document_id": "d", "file_checksum": "y" * 64, "page_number": 1}
        manifest = {"document_id": "d", "checksum": "x" * 64}
        with self.assertRaises(ValueError):
            validate_source_provenance([chunk], [span], [manifest])


if __name__ == "__main__":
    unittest.main()
