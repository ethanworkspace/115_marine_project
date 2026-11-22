import unittest

from src.evaluation.phase10_recovery import make_acquisition_manifest


class SourceAcquisitionManifestTests(unittest.TestCase):
    def test_manifest_records_download_identity_access_and_hash(self):
        row = make_acquisition_manifest(document_id="d", title="title", organization="org",
            source_url="https://example.org/source", publication_url="https://example.org/record",
            file_path="data/source.pdf", source_tier=1, download_date="2026-10-03",
            publication_date="2025-01-01", version="v1", checksum="a" * 64, size=123,
            parser_version="pymupdf", license_status="not_explicitly_stated",
            access_information="public government PDF", identity_status="verified",
            authority_status="verified_official", legal_status="unknown")
        self.assertEqual(row["checksum"], "a" * 64)
        self.assertEqual(row["legal_status"], "unknown")
        self.assertEqual(row["license_status"], "not_explicitly_stated")
        self.assertEqual(row["download_date"], "2026-10-03")

    def test_invalid_hash_and_legal_status_fail_closed(self):
        with self.assertRaises(ValueError):
            make_acquisition_manifest(document_id="d", title="t", organization="o", source_url=None,
                publication_url=None, file_path="x.pdf", source_tier=1, download_date="2026-10-03",
                publication_date=None, version=None, checksum="bad", size=1, parser_version="p",
                license_status="unknown", access_information="unknown", identity_status="unresolved",
                authority_status="unknown", legal_status="current")


if __name__ == "__main__":
    unittest.main()
