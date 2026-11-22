"""Read-only dataset and legacy-index quality profiling."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # PyMuPDF currently exports both names; support older installed versions.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibility path for older PyMuPDF
    import fitz  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[2]


def read_manifest(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"manifest line {line_number} must be a JSON object")
            records.append(value)
    return records


def _pdf_page_profile(files: Iterable[Path], repo_root: Path) -> dict[str, Any]:
    pdf_files = [path for path in files if path.suffix.lower() == ".pdf"]
    page_count = 0
    pages_without_text = 0
    errors: list[dict[str, str]] = []
    for path in pdf_files:
        try:
            with fitz.open(path) as document:
                page_count += len(document)
                pages_without_text += sum(
                    not page.get_text("text").strip() for page in document
                )
        except Exception as exc:
            errors.append(
                {
                    "file_path": path.resolve().relative_to(repo_root.resolve()).as_posix()
                    if path.resolve().is_relative_to(repo_root.resolve())
                    else path.name,
                    "error": str(exc),
                }
            )
    return {
        "file_count": len(pdf_files),
        "page_count": page_count,
        "pages_without_extractable_text": pages_without_text,
        "page_scan_errors": errors,
    }


def _read_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {"available": False, "chunk_count": 0, "duplicate_chunk_groups": 0, "duplicate_chunk_extra_rows": 0}
    uri = f"file:{index_path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks'"
            ).fetchone()
            if not table:
                return {"available": True, "chunk_count": 0, "error": "chunks table not found"}
            rows = connection.execute(
                "SELECT content, metadata_json, page FROM chunks"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {"available": True, "chunk_count": 0, "error": str(exc)}

    lengths = [len(row["content"] or "") for row in rows]
    content_groups: dict[str, int] = defaultdict(int)
    missing_species = 0
    missing_topic = 0
    missing_disease = 0
    missing_page = 0
    for row in rows:
        content = (row["content"] or "").strip()
        content_groups[hashlib.sha256(content.encode("utf-8")).hexdigest()] += 1
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        species = metadata.get("species", metadata.get("fish_species"))
        topic = metadata.get("topic", metadata.get("topics"))
        disease = metadata.get("disease", metadata.get("disease_name"))
        missing_species += not species or "未標記" in species
        missing_topic += not topic or "未標記" in topic
        missing_disease += not disease or "未標記" in disease
        page = metadata.get("page_start", row["page"])
        missing_page += page is None

    duplicate_groups = [count for count in content_groups.values() if count > 1]
    return {
        "available": True,
        "chunk_count": len(rows),
        "chunks_under_20_chars": sum(length < 20 for length in lengths),
        "chunks_under_100_chars": sum(length < 100 for length in lengths),
        "duplicate_chunk_groups": len(duplicate_groups),
        "duplicate_chunk_extra_rows": sum(count - 1 for count in duplicate_groups),
        "missing_species": missing_species,
        "missing_topic": missing_topic,
        "missing_disease": missing_disease,
        "missing_page": missing_page,
    }


def build_data_quality_report(
    data_dir: str | Path = ROOT / "my_data",
    manifest_records: list[dict[str, Any]] | None = None,
    index_path: str | Path = ROOT / "rag_store.sqlite3",
    repo_root: str | Path = ROOT,
) -> dict[str, Any]:
    root = Path(repo_root)
    directory = Path(data_dir)
    files = sorted(path for path in directory.rglob("*") if path.is_file()) if directory.exists() else []
    extensions = Counter(path.suffix.lower() or "[no extension]" for path in files)
    manifest = manifest_records or []
    index = _read_index(Path(index_path))
    pdf = _pdf_page_profile(files, root)
    duplicate_documents = [record for record in manifest if record.get("duplicate_of")]
    legal_unknown = sum(record.get("legal_status", "unknown") == "unknown" for record in manifest)
    missing_url = sum(not record.get("source_url") for record in manifest)
    unverified_sources = sum(
        record.get("source_id") == "unverified" or record.get("source_tier") is None
        for record in manifest
    )
    legacy_doc_files = [path for path in files if path.suffix.lower() == ".doc"]

    metrics = {
        "documents": {
            "count": len(files),
            "by_extension": dict(sorted(extensions.items())),
            "total_file_size_bytes": sum(path.stat().st_size for path in files),
            "source_url_missing": missing_url,
            "source_unverified_or_unranked": unverified_sources,
        },
        "pdf_pages": pdf,
        "duplicate_documents": {
            "count_marked_duplicate": len(duplicate_documents),
            "records": [
                {"document_id": record.get("document_id"), "duplicate_of": record.get("duplicate_of")}
                for record in duplicate_documents
            ],
        },
        "duplicate_chunks": {
            "groups": index.get("duplicate_chunk_groups", 0),
            "extra_rows": index.get("duplicate_chunk_extra_rows", 0),
        },
        "chunks": {
            "count": index.get("chunk_count", 0),
            "under_20_chars": index.get("chunks_under_20_chars", 0),
            "under_100_chars": index.get("chunks_under_100_chars", 0),
        },
        "metadata": {
            "missing_species": index.get("missing_species", 0),
            "missing_topic": index.get("missing_topic", 0),
            "missing_disease": index.get("missing_disease", 0),
            "missing_page": index.get("missing_page", 0),
        },
        "legal": {"unknown_legal_status": legal_unknown},
        "legacy_doc_files": {
            "count": len(legacy_doc_files),
            "paths": [
                path.resolve().relative_to(root.resolve()).as_posix()
                if path.resolve().is_relative_to(root.resolve())
                else path.name
                for path in legacy_doc_files
            ],
        },
    }

    issues: list[dict[str, Any]] = []

    def add_issue(issue_id: str, severity: str, count: int, message: str) -> None:
        if count:
            issues.append(
                {"id": issue_id, "severity": severity, "count": int(count), "message": message}
            )

    add_issue(
        "pdf_pages_without_text", "critical", pdf["pages_without_extractable_text"],
        "PDF pages have no extractable text; image-only content may be absent from text retrieval.",
    )
    add_issue("unknown_legal_status", "high", legal_unknown, "Document legal status is unknown and must not be treated as current.")
    add_issue("missing_source_url", "high", missing_url, "Document source URLs are not recorded.")
    add_issue("unverified_source", "high", unverified_sources, "Documents have unverified or unranked provenance.")
    add_issue("duplicate_documents", "high", len(duplicate_documents), "Exact duplicate files are marked; keep both records until reviewed.")
    add_issue("legacy_doc_files", "high", len(legacy_doc_files), "Legacy .doc files need conversion and extraction QA.")
    add_issue("missing_species", "high", metrics["metadata"]["missing_species"], "Chunks have no usable species tag.")
    add_issue("missing_topic", "high", metrics["metadata"]["missing_topic"], "Chunks have no usable topic tag.")
    add_issue("missing_disease", "high", metrics["metadata"]["missing_disease"], "Chunks have no usable disease tag.")
    add_issue("chunks_under_20_chars", "high", metrics["chunks"]["under_20_chars"], "Very short chunks may be noise or broken fragments.")
    add_issue("duplicate_chunks", "medium", metrics["duplicate_chunks"]["extra_rows"], "Exact duplicate chunk rows reduce retrieval diversity.")
    add_issue("chunks_under_100_chars", "medium", metrics["chunks"]["under_100_chars"], "Short chunks should be reviewed for lost context.")
    add_issue("missing_page", "medium", metrics["metadata"]["missing_page"], "Chunks lack a source page number.")
    add_issue("pdf_page_scan_errors", "medium", len(pdf["page_scan_errors"]), "Some PDF files could not be inspected for text coverage.")

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_directory": directory.relative_to(root).as_posix()
        if directory.resolve().is_relative_to(root.resolve())
        else str(directory),
        "index_path": Path(index_path).name,
        "metrics": metrics,
        "issues": issues,
        "severity_order": ["critical", "high", "medium", "low"],
    }


def write_data_quality_report(report: dict[str, Any], output_path: str | Path) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a read-only data quality report.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "my_data")
    parser.add_argument("--manifest", type=Path, default=ROOT / "reports" / "document_manifest.jsonl")
    parser.add_argument("--index", type=Path, default=ROOT / "rag_store.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "data_quality.json")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    records = read_manifest(args.manifest) if args.manifest.exists() else []
    report = build_data_quality_report(
        data_dir=args.data_dir,
        manifest_records=records,
        index_path=args.index,
        repo_root=args.repo_root,
    )
    write_data_quality_report(report, args.output)
    print(f"Wrote data quality report to {args.output}")
    print(json.dumps(report["metrics"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
