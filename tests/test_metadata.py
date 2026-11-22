from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.ingestion.metadata import (
    CHUNK_REQUIRED_FIELDS,
    DOCUMENT_REQUIRED_FIELDS,
    LEGAL_STATUSES,
    MetadataValidationError,
    merge_document_chunk_metadata,
    validate_chunk_metadata,
    validate_document_metadata,
)


ROOT = Path(__file__).resolve().parents[1]


def valid_document() -> dict:
    return {
        "document_id": "fb907dc9-1e95-5e04-8b92-b06a5790ba64",
        "title": "test document",
        "source_id": "unverified",
        "organization": None,
        "source_url": None,
        "source_tier": None,
        "publication_date": None,
        "download_date": None,
        "effective_date": None,
        "expiry_date": None,
        "version": None,
        "legal_status": "unknown",
        "species": [],
        "topics": [],
        "document_type": "unknown",
        "language": None,
        "checksum": "a" * 64,
        "file_path": "my_data/test.pdf",
        "file_size": 0,
        "parser_version": "test",
        "ingestion_status": "registered",
    }


def valid_chunk() -> dict:
    return {
        "chunk_id": "doc-1:chunk-1",
        "document_id": "fb907dc9-1e95-5e04-8b92-b06a5790ba64",
        "parent_chunk_id": None,
        "species": [],
        "topic": [],
        "disease": [],
        "chapter": None,
        "section": None,
        "page_start": None,
        "page_end": None,
        "content_checksum": "b" * 64,
        "extraction_confidence": None,
        "embedding_model": None,
        "embedding_version": None,
        "embedding_dimension": None,
    }


class MetadataTests(unittest.TestCase):
    def test_legal_status_is_restricted_to_allowed_values(self) -> None:
        self.assertEqual(
            LEGAL_STATUSES,
            ("current", "superseded", "repealed", "historical", "draft", "unknown"),
        )
        for status in LEGAL_STATUSES:
            record = valid_document()
            record["legal_status"] = status
            validate_document_metadata(record)
        invalid = valid_document()
        invalid["legal_status"] = "active"
        with self.assertRaises(MetadataValidationError):
            validate_document_metadata(invalid)

    def test_required_fields_match_json_schemas(self) -> None:
        document_schema = json.loads((ROOT / "schemas" / "document.schema.json").read_text(encoding="utf-8"))
        chunk_schema = json.loads((ROOT / "schemas" / "chunk.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(document_schema["required"]), set(DOCUMENT_REQUIRED_FIELDS))
        self.assertEqual(set(chunk_schema["required"]), set(CHUNK_REQUIRED_FIELDS))
        validate_document_metadata(valid_document())
        validate_chunk_metadata(valid_chunk())

    def test_missing_required_metadata_field_is_rejected(self) -> None:
        document = valid_document()
        del document["source_id"]
        with self.assertRaisesRegex(MetadataValidationError, "source_id"):
            validate_document_metadata(document)
        chunk = valid_chunk()
        del chunk["content_checksum"]
        with self.assertRaisesRegex(MetadataValidationError, "content_checksum"):
            validate_chunk_metadata(chunk)

    def test_chunk_metadata_overrides_document_defaults(self) -> None:
        document = {"document_id": "d1", "species": ["吳郭魚"], "topics": ["養殖"]}
        inherited = merge_document_chunk_metadata(document, {"chunk_id": "c1"})
        overridden = merge_document_chunk_metadata(
            document, {"chunk_id": "c2", "species": ["石斑魚"], "topic": ["疾病"]}
        )
        explicitly_empty = merge_document_chunk_metadata(
            document, {"chunk_id": "c3", "species": []}
        )
        self.assertEqual(inherited["species"], ["吳郭魚"])
        self.assertEqual(inherited["topic"], ["養殖"])
        self.assertEqual(overridden["species"], ["石斑魚"])
        self.assertEqual(overridden["topic"], ["疾病"])
        self.assertEqual(explicitly_empty["species"], [])


if __name__ == "__main__":
    unittest.main()
