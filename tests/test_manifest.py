from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ingestion.manifest import build_manifest, write_manifest
from src.ingestion.metadata import MetadataValidationError


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "my_data"
        self.data_dir.mkdir()
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        self.sources_path = self.config_dir / "sources.yaml"
        self.sources_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "source_id": "unverified",
                            "organization": None,
                            "source_tier": None,
                            "source_type": "unverified",
                            "trusted_for": [],
                            "homepage": None,
                            "notes": "unverified",
                        },
                        {
                            "source_id": "official",
                            "organization": "Test agency",
                            "source_tier": 1,
                            "source_type": "government_agency",
                            "trusted_for": ["regulations"],
                            "homepage": None,
                            "notes": "test",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.overrides_path = self.config_dir / "document_overrides.json"
        self.overrides_path.write_text(
            json.dumps(
                {
                    "documents": {
                        "my_data/official.txt": {
                            "source_id": "official",
                            "source_url": "https://example.org/document",
                            "legal_status": "current",
                            "species": ["吳郭魚"],
                            "topics": ["水質"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build(self) -> list[dict]:
        return build_manifest(
            data_dir=self.data_dir,
            repo_root=self.root,
            sources_path=self.sources_path,
            overrides_path=self.overrides_path,
            index_path=None,
        )

    def test_document_id_is_stable_and_exact_duplicates_are_marked(self) -> None:
        (self.data_dir / "a.txt").write_text("same content", encoding="utf-8")
        (self.data_dir / "b.txt").write_text("same content", encoding="utf-8")

        first_run = self._build()
        second_run = self._build()

        self.assertEqual([row["document_id"] for row in first_run], [row["document_id"] for row in second_run])
        self.assertIsNone(first_run[0]["duplicate_of"])
        self.assertEqual(first_run[1]["duplicate_of"], first_run[0]["document_id"])
        self.assertTrue((self.data_dir / "a.txt").exists())
        self.assertTrue((self.data_dir / "b.txt").exists())

    def test_manifest_uses_explicit_document_overrides_and_unknown_defaults(self) -> None:
        (self.data_dir / "official.txt").write_text("official content", encoding="utf-8")
        (self.data_dir / "unreviewed.pdf").write_bytes(b"placeholder")

        records = self._build()
        official, unreviewed = records
        self.assertEqual(official["source_id"], "official")
        self.assertEqual(official["source_tier"], 1)
        self.assertEqual(official["organization"], "Test agency")
        self.assertEqual(official["legal_status"], "current")
        self.assertEqual(unreviewed["source_id"], "unverified")
        self.assertIsNone(unreviewed["source_tier"])
        self.assertIsNone(unreviewed["publication_date"])
        self.assertEqual(unreviewed["legal_status"], "unknown")

    def test_manifest_serialization_round_trips_jsonl(self) -> None:
        (self.data_dir / "species.txt").write_text("吳郭魚", encoding="utf-8")
        records = self._build()
        output = self.root / "reports" / "manifest.jsonl"
        write_manifest(records, output)
        round_trip = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(round_trip, records)

    def test_invalid_legal_status_override_fails_manifest_build(self) -> None:
        (self.data_dir / "official.txt").write_text("text", encoding="utf-8")
        config = json.loads(self.overrides_path.read_text(encoding="utf-8"))
        config["documents"]["my_data/official.txt"]["legal_status"] = "active"
        self.overrides_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaises(MetadataValidationError):
            self._build()


if __name__ == "__main__":
    unittest.main()
