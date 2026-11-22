"""Build stable, provenance-aware JSONL manifests for source documents.

`config/sources.yaml` is authored as a JSON-compatible YAML 1.2 document so the
manifest builder can use only the Python standard library. Unknown provenance is
kept unknown; filenames and chunk text are not used to promote source metadata.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .checksum import normalize_document_path, sha256_file, stable_document_id
from .metadata import validate_document_metadata


ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".odt", ".txt", ".md"}
DEFAULT_PARSER_VERSION = "rag_core_legacy"
OVERRIDE_FIELDS = {
    "title",
    "source_id",
    "source_url",
    "publication_date",
    "download_date",
    "effective_date",
    "expiry_date",
    "version",
    "legal_status",
    "species",
    "topics",
    "document_type",
    "language",
}


def _load_json_yaml(path: Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML subset used by the source registry."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot read {path}: source registry must be valid JSON-compatible YAML 1.2"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a top-level object")
    return value


def load_source_registry(path: str | Path) -> dict[str, dict[str, Any]]:
    config = _load_json_yaml(Path(path))
    records = config.get("sources")
    if not isinstance(records, list):
        raise ValueError("source registry must contain a 'sources' list")
    registry: dict[str, dict[str, Any]] = {}
    required = {
        "source_id",
        "organization",
        "source_tier",
        "source_type",
        "trusted_for",
        "homepage",
        "notes",
    }
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each source registry item must be an object")
        missing = sorted(required - record.keys())
        if missing:
            raise ValueError(f"source registry item missing fields: {', '.join(missing)}")
        source_id = record["source_id"]
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be a non-empty string")
        if source_id in registry:
            raise ValueError(f"duplicate source_id in registry: {source_id}")
        tier = record["source_tier"]
        if tier is not None and (isinstance(tier, bool) or tier not in (1, 2, 3, 4)):
            raise ValueError(f"invalid source_tier for {source_id}: {tier}")
        if record["organization"] is not None and not isinstance(record["organization"], str):
            raise ValueError(f"organization for {source_id} must be a string or null")
        if not isinstance(record["source_type"], str) or not record["source_type"].strip():
            raise ValueError(f"source_type for {source_id} must be a non-empty string")
        if record["homepage"] is not None:
            homepage = urlparse(record["homepage"])
            if homepage.scheme not in ("http", "https") or not homepage.netloc:
                raise ValueError(f"homepage for {source_id} must be an absolute HTTP(S) URL or null")
        if not isinstance(record["notes"], str):
            raise ValueError(f"notes for {source_id} must be a string")
        if not isinstance(record["trusted_for"], list) or not all(
            isinstance(item, str) for item in record["trusted_for"]
        ):
            raise ValueError(f"trusted_for for {source_id} must be a list of strings")
        registry[source_id] = record
    if "unverified" not in registry:
        raise ValueError("source registry must include the 'unverified' source")
    return registry


def _load_overrides(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("document overrides must be a top-level object")
    documents = config.get("documents", config)
    if not isinstance(documents, dict):
        raise ValueError("document overrides must be an object keyed by file_path")
    normalized: dict[str, dict[str, Any]] = {}
    for file_path, values in documents.items():
        if not isinstance(values, dict):
            raise ValueError(f"document override for {file_path} must be an object")
        unknown = sorted(set(values) - OVERRIDE_FIELDS)
        if unknown:
            raise ValueError(
                f"unsupported document override fields for {file_path}: {', '.join(unknown)}"
            )
        normalized[normalize_document_path(file_path)] = values
    return normalized


def _indexed_sources(index_path: str | Path | None) -> set[str]:
    if index_path is None or not Path(index_path).exists():
        return set()
    path = Path(index_path).resolve()
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT DISTINCT source FROM chunks").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return set()
    return {normalize_document_path(row[0]) for row in rows if row and row[0]}


def _manifest_path(path: Path, repo_root: Path, data_dir: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return (Path(data_dir.name) / path.resolve().relative_to(data_dir.resolve())).as_posix()


def build_manifest(
    data_dir: str | Path = ROOT / "my_data",
    repo_root: str | Path = ROOT,
    sources_path: str | Path = ROOT / "config" / "sources.yaml",
    overrides_path: str | Path | None = ROOT / "config" / "document_overrides.json",
    index_path: str | Path | None = ROOT / "rag_store.sqlite3",
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> list[dict[str, Any]]:
    """Build manifest records without deleting or rewriting any source file."""
    data_root = Path(data_dir)
    root = Path(repo_root)
    if not data_root.exists():
        raise FileNotFoundError(f"data directory does not exist: {data_root}")

    registry = load_source_registry(sources_path)
    overrides = _load_overrides(overrides_path)
    indexed = _indexed_sources(index_path)
    files = sorted(
        (
            path
            for path in data_root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda path: _manifest_path(path, root, data_root).casefold(),
    )

    manifests: list[dict[str, Any]] = []
    first_by_checksum: dict[str, str] = {}
    for path in files:
        file_path = _manifest_path(path, root, data_root)
        override = overrides.get(normalize_document_path(file_path), {})
        source_id = override.get("source_id", "unverified")
        if source_id not in registry:
            raise ValueError(f"unknown source_id {source_id!r} for {file_path}")
        source = registry[source_id]
        checksum = sha256_file(path)
        document_id = stable_document_id(file_path)
        record: dict[str, Any] = {
            "document_id": document_id,
            "title": path.stem,
            "source_id": source_id,
            "organization": source["organization"],
            "source_url": None,
            "source_tier": source["source_tier"],
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
            "checksum": checksum,
            "file_path": file_path,
            "file_size": path.stat().st_size,
            "parser_version": parser_version,
            "ingestion_status": "indexed" if normalize_document_path(file_path) in indexed else "registered",
            "duplicate_of": first_by_checksum.get(checksum),
        }
        for field, value in override.items():
            if field == "source_id":
                continue
            record[field] = value
        if checksum not in first_by_checksum:
            first_by_checksum[checksum] = document_id
        validate_document_metadata(record)
        manifests.append(record)
    return manifests


def write_manifest(records: list[dict[str, Any]], output_path: str | Path) -> None:
    """Validate all records, then atomically write UTF-8 JSON Lines."""
    for record in records:
        validate_document_metadata(record)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stable document manifests (JSONL).")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "my_data")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--sources", type=Path, default=ROOT / "config" / "sources.yaml")
    parser.add_argument(
        "--overrides", type=Path, default=ROOT / "config" / "document_overrides.json"
    )
    parser.add_argument("--index", type=Path, default=ROOT / "rag_store.sqlite3")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports" / "document_manifest.jsonl"
    )
    parser.add_argument("--parser-version", default=DEFAULT_PARSER_VERSION)
    args = parser.parse_args()
    records = build_manifest(
        data_dir=args.data_dir,
        repo_root=args.repo_root,
        sources_path=args.sources,
        overrides_path=args.overrides,
        index_path=args.index,
        parser_version=args.parser_version,
    )
    write_manifest(records, args.output)
    duplicates = sum(record["duplicate_of"] is not None for record in records)
    print(
        f"Wrote {len(records)} document records to {args.output}; "
        f"exact duplicate documents marked: {duplicates}"
    )


if __name__ == "__main__":
    main()
