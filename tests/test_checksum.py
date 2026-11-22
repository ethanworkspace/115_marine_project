from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from src.ingestion.checksum import (
    find_duplicate_files,
    sha256_file,
    stable_document_id,
)


class ChecksumTests(unittest.TestCase):
    def test_sha256_file_matches_standard_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_bytes(b"marine evidence")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"marine evidence").hexdigest())

    def test_document_id_is_stable_and_normalizes_windows_paths(self) -> None:
        first = stable_document_id("my_data\\species\\tilapia.pdf")
        second = stable_document_id("MY_DATA/species/tilapia.pdf")
        self.assertEqual(first, second)
        self.assertEqual(first, stable_document_id("my_data/species/tilapia.pdf"))

    def test_exact_duplicate_files_are_reported_without_deleting_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "a.txt"
            duplicate = root / "b.txt"
            canonical.write_bytes(b"same bytes")
            duplicate.write_bytes(b"same bytes")

            result = find_duplicate_files([canonical, duplicate])

            self.assertEqual(result, {str(duplicate): str(canonical)})
            self.assertTrue(canonical.exists())
            self.assertTrue(duplicate.exists())


if __name__ == "__main__":
    unittest.main()
