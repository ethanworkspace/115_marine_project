"""Capture a read-only snapshot of the current legacy RAG index and inputs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - older PyMuPDF compatibility
    import fitz  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "my_data"
DB_PATH = ROOT / "rag_store.sqlite3"
OUTPUT_DIR = ROOT / "reports" / "baseline"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _ollama_runtime_observation() -> dict[str, Any]:
    """Inspect the configured loopback Ollama only; never contact remote hosts."""
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    is_loopback = urlparse(host).hostname in ("127.0.0.1", "localhost", "::1")
    result: dict[str, Any] = {
        "loopback_endpoint_checked": is_loopback,
        "reachable": False,
        "configured_embedding_model": os.environ.get("EMBED_MODEL", "bge-m3:latest"),
        "models": None,
        "note": None,
    }
    if not is_loopback:
        result["note"] = "Configured Ollama host is not loopback; it was not contacted by this report script."
        return result
    try:
        response = requests.get(f"{host}/api/tags", timeout=2)
        response.raise_for_status()
        result["reachable"] = True
        result["models"] = [
            {
                "name": model.get("name"),
                "digest": model.get("digest"),
                "size_bytes": model.get("size"),
                "format": model.get("details", {}).get("format"),
                "parameter_size": model.get("details", {}).get("parameter_size"),
                "quantization_level": model.get("details", {}).get("quantization_level"),
            }
            for model in response.json().get("models", [])
        ]
    except (requests.RequestException, ValueError, TypeError):
        result["note"] = "Loopback Ollama /api/tags was unavailable or returned invalid JSON."
    return result


def _read_index() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"available": False, "path": "rag_store.sqlite3"}

    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]: row["sql"]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            )
        }
        if "chunks" not in tables:
            return {
                "available": True,
                "path": "rag_store.sqlite3",
                "size_bytes": DB_PATH.stat().st_size,
                "error": "chunks table not found",
            }

        rows = connection.execute(
            "SELECT content, source, page, metadata_json, embedding FROM chunks"
        ).fetchall()
        content_lengths = [len(row["content"]) for row in rows]
        embedding_dimensions = sorted(
            {len(row["embedding"]) // 4 for row in rows if row["embedding"] is not None}
        )
        duplicate_hashes: dict[str, int] = defaultdict(int)
        for row in rows:
            normalized = row["content"].strip()
            duplicate_hashes[hashlib.sha256(normalized.encode("utf-8")).hexdigest()] += 1

        doc_types: Counter[str] = Counter()
        species: Counter[str] = Counter()
        unmarked_species = 0
        unmarked_disease = 0
        missing_page = 0
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            doc_types[str(metadata.get("doc_type") or "missing")] += 1
            tags = metadata.get("fish_species") or []
            if not tags or "未標記" in tags:
                unmarked_species += 1
            species.update(tag for tag in tags if tag != "未標記")
            diseases = metadata.get("disease_name") or []
            if not diseases or "未標記" in diseases:
                unmarked_disease += 1
            if row["page"] is None:
                missing_page += 1

        try:
            fts_count = connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        except sqlite3.Error:
            fts_count = None

        return {
            "available": True,
            "path": "rag_store.sqlite3",
            "size_bytes": DB_PATH.stat().st_size,
            "chunk_count": len(rows),
            "indexed_source_count": len({row["source"] for row in rows}),
            "fts_row_count": fts_count,
            "embedding_dimensions_observed": embedding_dimensions,
            "embedding_storage": "Float32 BLOB (dimension inferred from byte length)",
            "content_characters": {
                "min": min(content_lengths) if content_lengths else None,
                "median": statistics.median(content_lengths) if content_lengths else None,
                "mean": round(statistics.mean(content_lengths), 2) if content_lengths else None,
                "max": max(content_lengths) if content_lengths else None,
                "under_20": sum(length < 20 for length in content_lengths),
                "under_100": sum(length < 100 for length in content_lengths),
            },
            "duplicate_chunk_groups": sum(count > 1 for count in duplicate_hashes.values()),
            "duplicate_chunk_extra_rows": sum(
                count - 1 for count in duplicate_hashes.values() if count > 1
            ),
            "document_types_by_chunk": dict(doc_types),
            "species_tag_occurrences": dict(species),
            "unmarked_species_chunks": unmarked_species,
            "unmarked_disease_chunks": unmarked_disease,
            "missing_page_chunks": missing_page,
            "tables": tables,
        }


def _profile_dataset() -> dict[str, Any]:
    files = sorted(path for path in DATA_DIR.rglob("*") if path.is_file()) if DATA_DIR.exists() else []
    by_extension = Counter(path.suffix.lower() or "[no extension]" for path in files)
    file_hashes: dict[str, list[str]] = defaultdict(list)
    for path in files:
        file_hashes[_sha256(path)].append(path.relative_to(ROOT).as_posix())

    pdf_count = 0
    pdf_pages = 0
    pages_without_text = 0
    page_scan_errors: list[dict[str, str]] = []
    for path in files:
        if path.suffix.lower() != ".pdf":
            continue
        pdf_count += 1
        try:
            with fitz.open(path) as document:
                pdf_pages += len(document)
                pages_without_text += sum(
                    not page.get_text("text").strip() for page in document
                )
        except Exception as exc:  # Preserve profile generation if one input is unreadable.
            page_scan_errors.append(
                {"file_path": path.relative_to(ROOT).as_posix(), "error": str(exc)}
            )

    index = _read_index()
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(),
        "data_directory": "my_data",
        "data_is_git_tracked": False,
        "document_count": len(files),
        "document_count_by_extension": dict(sorted(by_extension.items())),
        "pdf_file_count": pdf_count,
        "pdf_page_count": pdf_pages,
        "pdf_pages_without_extractable_text": pages_without_text,
        "pdf_page_scan_errors": page_scan_errors,
        "duplicate_document_groups": [paths for paths in file_hashes.values() if len(paths) > 1],
        "chunk_count": index.get("chunk_count"),
        "index": index,
        "notes": [
            "This is a snapshot of local ignored inputs and the local SQLite index.",
            "The embedding model used to build the existing index is not stored and is unknown.",
        ],
    }


def _retrieval_config(profile: dict[str, Any]) -> dict[str, Any]:
    dimensions = profile["index"].get("embedding_dimensions_observed") or []
    ollama_runtime = _ollama_runtime_observation()
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "rag_core.py code inspection; runtime environment may override OLLAMA_HOST and EMBED_MODEL",
        "embedding": {
            "indexed_model": "unknown",
            "code_default_model": "bge-m3:latest",
            "dimension_observed_in_index": dimensions[0] if len(dimensions) == 1 else None,
            "dimensions_observed_in_index": dimensions,
            "dimension_is_not_model_provenance": True,
        },
        "bm25": {
            "backend": "SQLite FTS5",
            "order_by": "bm25(chunks_fts)",
            "indexed_text": "build_embed_text(metadata, content), expanded by cjk_tokens",
            "cjk_tokenization": ["unigram", "bigram", "trigram"],
            "fts5_tokenizer": "SQLite FTS5 default tokenizer (no custom tokenizer configured)",
            "query_construction": "CJK-expanded query tokens joined with OR",
            "candidate_limit": "top_k * 8",
            "lexical_fusion_score": "1 / (rank + 2); raw bm25 value is used for ordering, not fusion",
        },
        "dense_retrieval": {
            "backend": "SQLite BLOBs + Python cosine",
            "search": "exact full scan of all stored vectors",
            "query_embedding_model_code_default": "bge-m3:latest",
            "query_embedding_model_runtime_configuration": ollama_runtime["configured_embedding_model"],
            "candidate_limit": "top_k * 8",
        },
        "hybrid_fusion": {
            "type": "weighted sum; not standard RRF",
            "default_weights": {"dense_cosine": 0.55, "lexical_rank_score": 0.45},
            "when_query_contains_species_or_known_disease": {
                "dense_cosine": 0.42,
                "lexical_rank_score": 0.58,
            },
            "exact_term_bonus": 0.08,
            "metadata_filter_timing": "after retrieval and score fusion",
            "metadata_filters": ["fish_species", "doc_type", "disease_name"],
            "reranker": "none",
        },
        "top_k": {
            "default": 5,
            "streamlit_range": [1, 12],
            "cli_default": 5,
        },
        "llm": {
            "backend": "Ollama /api/chat",
            "model_choices": ["gemma2:9b", "deepseek-r1:8b", "qwen2.5-coder:7b", "deepseek-r1:7b"],
            "default_model": "gemma2:9b",
            "local_ollama_runtime_observation": ollama_runtime,
            "stream": False,
            "generation_parameters": "not explicitly set by application",
            "ollama_host_code_default": "http://127.0.0.1:11434; may be overridden by OLLAMA_HOST",
        },
    }


def _index_info(profile: dict[str, Any]) -> dict[str, Any]:
    index = profile["index"]
    dimensions = index.get("embedding_dimensions_observed") or []
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": index.get("path"),
        "database_available": index.get("available"),
        "database_size_bytes": index.get("size_bytes"),
        "document_count_in_data_directory": profile["document_count"],
        "indexed_source_count": index.get("indexed_source_count"),
        "chunk_count": index.get("chunk_count"),
        "fts_row_count": index.get("fts_row_count"),
        "embedding_dimension": dimensions[0] if len(dimensions) == 1 else None,
        "embedding_dimensions_observed": dimensions,
        "embedding_model": "unknown",
        "code_default_embedding_model": "bge-m3:latest",
        "embedding_model_provenance_note": "No model identifier/version is stored in the current SQLite schema.",
        "schema": index.get("tables", {}),
    }


def _architecture_markdown(profile: dict[str, Any]) -> str:
    index = profile["index"]
    return f"""# Current RAG Architecture Baseline

Captured at: {datetime.now(timezone.utc).isoformat()}
Git revision: `{profile.get('git_revision') or 'unknown'}`

## Baseline status before governance changes

- Working tree was clean before this report was generated.
- No tracked or local `tests/` directory was present. The virtual environment did not have pytest installed (`python -m pytest --version` failed with `No module named pytest`).
- Streamlit was started with `python -m streamlit run app.py --server.headless true --server.port 8505`; both `/_stcore/health` and `/` returned HTTP 200. The smoke-test process was stopped afterward.
- Local inputs and the SQLite database are ignored by Git; this report describes the current machine's snapshot.

## Current data and index

- Documents: {profile['document_count']} ({profile['document_count_by_extension']})
- PDF pages: {profile['pdf_page_count']}; pages without extractable text: {profile['pdf_pages_without_extractable_text']}
- Indexed sources: {index.get('indexed_source_count', 'unknown')}
- Chunks: {index.get('chunk_count', 'unknown')}
- Observed embedding dimension: {index.get('embedding_dimensions_observed', 'unknown')}
- Embedding model that created the existing index: **unknown**. The code default is `bge-m3:latest`, but the model identifier is not stored in the DB.

## Ingestion and retrieval

`build_index.py` scans `my_data/`; `rag_core.py` extracts PDF/DOC/DOCX/ODT/text, applies line-noise and term replacement rules, then heading-detects and character-chunks content. Metadata is inferred from chunk text and filename. Ollama `/api/embed` creates vectors stored as Float32 BLOBs in SQLite; expanded CJK text is indexed in FTS5.

At query time `retrieve()` runs FTS5 BM25 ordering and an exact Python cosine scan, combines a reciprocal-rank-like lexical score with raw cosine using a weighted sum, applies metadata filters after retrieval, and returns Top-K. This is **not standard RRF**. There is no query rewrite or reranker.

`ask_ollama()` sends concatenated context and the question as a user message to Ollama `/api/chat`; the model choices are `gemma2:9b`, `deepseek-r1:8b`, `qwen2.5-coder:7b`, and `deepseek-r1:7b`. When loopback Ollama is available, installed tags, digests, and quantization are captured in `retrieval_config.json`; the application does not log which model was selected for each query, and hardware is not recorded. The prompt requests citations and abstention but neither is validated. No evaluation pipeline or deterministic calculation engine exists.

## Frozen behavior

This baseline describes the pre-v2 retrieval ranking, embedding configuration, vector storage technology, LLM choices, and answer path. Governance additions must not change those behaviors.
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile = _profile_dataset()
    reports = {
        "dataset_profile.json": profile,
        "retrieval_config.json": _retrieval_config(profile),
        "index_info.json": _index_info(profile),
    }
    for name, report in reports.items():
        (OUTPUT_DIR / name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (OUTPUT_DIR / "current_architecture.md").write_text(
        _architecture_markdown(profile), encoding="utf-8"
    )
    print(f"Wrote baseline snapshot to {OUTPUT_DIR.relative_to(ROOT).as_posix()}")
    print(
        f"documents={profile['document_count']} chunks="
        f"{profile['index'].get('chunk_count', 'unknown')}"
    )


if __name__ == "__main__":
    main()
