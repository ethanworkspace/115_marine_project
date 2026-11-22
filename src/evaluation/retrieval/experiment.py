"""Experiment manifest schema validation helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any


REQUIRED_MANIFEST_FIELDS = (
    "experiment_id", "timestamp", "evaluation_corpus_sha256", "gold_dataset_sha256",
    "retriever_type", "retriever_config", "chunking_version", "embedding_model",
    "embedding_dimension", "top_k", "git_commit", "notes",
)


def validate_experiment_manifest(manifest: dict[str, Any]) -> list[str]:
    errors = [f"missing {key}" for key in REQUIRED_MANIFEST_FIELDS if key not in manifest]
    timestamp = manifest.get("timestamp")
    if timestamp:
        try:
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            errors.append("timestamp must be ISO-8601")
    for key in ("evaluation_corpus_sha256", "gold_dataset_sha256"):
        value = manifest.get(key)
        if value is not None and (len(str(value)) != 64 or any(char not in "0123456789abcdef" for char in str(value))):
            errors.append(f"{key} must be a lowercase SHA-256")
    return errors
