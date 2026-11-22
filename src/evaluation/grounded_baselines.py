"""Reproducible E1/E2 baselines for the frozen corpus-grounded Silver benchmark.

This module is evaluation-only. It never imports production retrieval or opens the
production SQLite store. Grounded evidence is consulted only after ranking.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import random
import subprocess
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .retrieval.metrics import metric_bundle
from .retrieval.models import GoldEvidence, ResolvedGold, RetrievalResult
from .retrievers.bm25 import BM25_CONFIG, TOKENIZER, EvaluationBM25
from .retrievers.ollama_dense import EvaluationDense
from .silver import _eligible_corpus


TOP_K = (1, 3, 5, 10)
GRANULARITIES = ("chunk", "page", "document")
OVERLAP_BUCKETS = {"low": (None, 0.35), "medium": (0.35, 0.55), "high": (0.55, None)}
BOOTSTRAP_SEED = 12012
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_METRICS = ("recall@5", "recall@10", "mrr", "ndcg@10")
ERROR_TAXONOMY = (
    "no_relevant_retrieved", "relevant_below_k", "wrong_document",
    "correct_document_wrong_page", "correct_page_wrong_chunk",
    "duplicate_competition", "metadata_filter_error", "query_term_mismatch", "multi_document_partial", "unknown",
)
SPECIES_REPORT_ORDER = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚", "unknown")
CATEGORY_REPORT_ORDER = ("disease", "fact", "water_quality", "sop", "climate", "calculation")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at {path}:{line_number}")
        rows.append(value)
    return rows


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def get_git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def retrieval_corpus(corpus_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use canonical first-stage retrieval records only, without Gold eligibility filtering."""
    selected = _eligible_corpus(corpus_rows)
    if any(row.get("retrieval_role") != "retrieval" for row in selected):
        raise ValueError("Non-retrieval role leaked into first-stage corpus")
    if any(row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"} for row in selected):
        raise ValueError("Non-canonical duplicate leaked into first-stage corpus")
    if any(row.get("canonical_chunk_id") != row.get("chunk_id") for row in selected):
        raise ValueError("Non-canonical chunk leaked into first-stage corpus")
    if any(row.get("canonical_document_id") != row.get("document_id") for row in selected):
        raise ValueError("Non-canonical document leaked into first-stage corpus")
    return selected


def _row_pages(row: dict[str, Any]) -> set[tuple[str, int]]:
    document_id = str(row.get("document_id") or "")
    pages = row.get("pages") or []
    if pages:
        return {(document_id, int(page)) for page in pages if page is not None}
    start = row.get("page_start") or row.get("page")
    end = row.get("page_end") or start
    if start is None:
        return set()
    return {(document_id, page) for page in range(int(start), int(end) + 1)}


def corpus_profile(rows: list[dict[str, Any]]) -> dict[str, int]:
    documents = {str(row.get("document_id")) for row in rows}
    pages = set().union(*(_row_pages(row) for row in rows)) if rows else set()
    return {"retrieval_chunk_count": len(rows), "document_count": len(documents), "page_count": len(pages)}


def validate_frozen_inputs(root: Path) -> dict[str, Any]:
    paths = {
        "evaluation_corpus_v2": root / "data/evaluation/corpus_v2.jsonl",
        "grounded_questions_v1": root / "data/evaluation/grounded/questions_v1.jsonl",
        "evidence_pool_v1": root / "data/evaluation/grounded/evidence_pool_v1.jsonl",
    }
    manifest_path = root / "reports/evaluation/grounded/manifest_v1.json"
    phase_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    expected = {
        "evaluation_corpus_v2": phase_manifest.get("evaluation_corpus_sha256"),
        "grounded_questions_v1": phase_manifest.get("question_dataset_sha256"),
        "evidence_pool_v1": phase_manifest.get("evidence_pool_sha256"),
    }
    mismatches = {name: {"expected": expected[name], "actual": hashes[name]}
                  for name in paths if hashes[name] != expected[name]}
    if mismatches:
        raise RuntimeError(f"Phase 11 frozen input checksum mismatch: {mismatches}")
    corpus_all = read_jsonl(paths["evaluation_corpus_v2"])
    questions = read_jsonl(paths["grounded_questions_v1"])
    pool = read_jsonl(paths["evidence_pool_v1"])
    if len(questions) != 169 or phase_manifest.get("generation_accepted_count") != 169:
        raise RuntimeError(f"Expected 169 grounded Silver questions, found {len(questions)}")
    corpus = retrieval_corpus(corpus_all)
    corpus_by_chunk = {str(row["chunk_id"]): row for row in corpus}
    all_by_chunk = {str(row["chunk_id"]): row for row in corpus_all}
    resolution: list[dict[str, Any]] = []
    for question in questions:
        if question.get("benchmark_type") != "silver" or question.get("generation_source") != "corpus_grounded_ai":
            raise RuntimeError(f"Question is not grounded Silver: {question.get('question_id')}")
        if question.get("evaluation_corpus_sha256") != hashes["evaluation_corpus_v2"]:
            raise RuntimeError(f"Question corpus provenance mismatch: {question.get('question_id')}")
        chunks = [str(value) for value in question.get("required_chunks") or []]
        if not chunks:
            raise RuntimeError(f"No required evidence chunks: {question.get('question_id')}")
        resolved: list[dict[str, Any]] = []
        for chunk_id in chunks:
            row = corpus_by_chunk.get(chunk_id)
            if row is None:
                nonretrieval = all_by_chunk.get(chunk_id)
                state = "non_retrieval_role" if nonretrieval and nonretrieval.get("retrieval_role") != "retrieval" else "missing_or_noncanonical"
                raise RuntimeError(f"Required evidence cannot resolve to retrieval corpus ({state}): {question.get('question_id')} {chunk_id}")
            resolved.append(row)
        snapshots = {str(item.get("chunk_id")): item for item in question.get("evidence_snapshot") or []}
        if set(snapshots) != set(chunks):
            raise RuntimeError(f"Evidence snapshot coverage mismatch: {question.get('question_id')}")
        for row in resolved:
            snapshot = snapshots[str(row["chunk_id"])]
            content = str(snapshot.get("text_snapshot") or "")
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if checksum != row.get("content_checksum") or checksum != snapshot.get("content_checksum"):
                raise RuntimeError(f"Evidence snapshot checksum mismatch: {question.get('question_id')} {row['chunk_id']}")
            if content != str(row.get("text") or ""):
                raise RuntimeError(f"Evidence snapshot text mismatch: {question.get('question_id')} {row['chunk_id']}")
        actual_documents = {str(row.get("document_id")) for row in resolved}
        required_documents = {str(value) for value in question.get("required_documents") or []}
        if not required_documents or actual_documents != required_documents:
            raise RuntimeError(f"Required document mismatch: {question.get('question_id')}")
        actual_pages = set().union(*(_row_pages(row) for row in resolved))
        required_pages = {(str(item.get("document_id")), int(item["page"]))
                          for item in question.get("required_pages") or [] if item.get("page") is not None}
        if not required_pages or not required_pages.issubset(actual_pages):
            raise RuntimeError(f"Required page mismatch: {question.get('question_id')}")
        resolution.append({
            "question_id": question["question_id"],
            "required_chunks": chunks,
            "required_pages": sorted([[document, page] for document, page in required_pages]),
            "required_documents": sorted(required_documents),
            "resolved_chunk_count": len(resolved),
            "snapshots_valid": True,
        })
    ids = [str(row.get("question_id")) for row in questions]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Duplicate question_id in Grounded Silver v1")
    evidence_hash = stable_sha256(resolution)
    return {
        "paths": paths,
        "hashes": hashes,
        "phase11_manifest": phase_manifest,
        "corpus_all": corpus_all,
        "corpus": corpus,
        "questions": questions,
        "evidence_pool": pool,
        "resolution": resolution,
        "evidence_resolution_sha256": evidence_hash,
        "corpus_profile": corpus_profile(corpus),
        "corpus_chunk_ids_sha256": stable_sha256(sorted(str(row["chunk_id"]) for row in corpus)),
        "question_ids_sha256": stable_sha256(sorted(ids)),
    }


class OllamaEmbeddingRuntime:
    """Small HTTP adapter for a locally running Ollama embedding model."""

    def __init__(self, *, base_url: str = "http://127.0.0.1:11434", model: str = "bge-m3:latest", timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.metadata: dict[str, Any] = {}
        self.dimension: int | None = None

    def _request(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read())
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama {endpoint} request failed: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Ollama {endpoint} returned a non-object response")
        return value

    def preflight(self) -> dict[str, Any]:
        version = self._request("api/version").get("version")
        tags_response = self._request("api/tags")
        model_row = next((row for row in tags_response.get("models", []) if row.get("name") == self.model), None)
        if model_row is None:
            raise RuntimeError(f"Required BGE-M3 model tag unavailable: {self.model}")
        show = self._request("api/show", {"model": self.model})
        details = model_row.get("details") or {}
        model_info = show.get("model_info") or {}
        expected_dimension = details.get("embedding_length")
        if expected_dimension is None:
            expected_dimension = next((value for key, value in model_info.items() if key.endswith("embedding_length")), None)
        if expected_dimension is None:
            raise RuntimeError("BGE-M3 model metadata does not report embedding dimension")
        probe_text = "台灣水產養殖文件檢索預檢"
        probe = self.embed_texts([probe_text])
        probe_again = self.embed_texts([probe_text])
        dimension = len(probe[0])
        if dimension != int(expected_dimension):
            raise RuntimeError(f"BGE-M3 embedding dimension mismatch: metadata={expected_dimension}, runtime={dimension}")
        ps = self._request("api/ps")
        running = next((row for row in ps.get("models", []) if row.get("name") == self.model), {})
        size_vram = running.get("size_vram")
        self.dimension = dimension
        self.metadata = {
            "model_name": self.model,
            "model_tag": model_row.get("name"),
            "model_digest": model_row.get("digest"),
            "model_family": details.get("family"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "model_context_length": details.get("context_length"),
            "runtime": "Ollama local HTTP /api/embed",
            "runtime_version": version,
            "embedding_dimension": dimension,
            "normalization": "explicit L2 unit normalization in evaluation process",
            "distance_metric": "cosine similarity (dot product over L2-normalized vectors)",
            "batch_size": 32,
            "device": "Ollama runtime; VRAM allocation reported" if isinstance(size_vram, int) and size_vram > 0 else "Ollama runtime; accelerator not confirmed",
            "runtime_size_vram_bytes": size_vram,
            "accelerator_model": "unknown (Ollama API does not expose a device name here)",
            "truncate": False,
            "embedding_repeat_probe_exact": probe[0] == probe_again[0],
            "embedding_repeat_probe_max_abs_delta": max((abs(a - b) for a, b in zip(probe[0], probe_again[0])), default=0.0),
        }
        return dict(self.metadata)

    def embed_texts(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []
        output: list[list[float]] = []
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset:offset + batch_size]
            response = self._request("api/embed", {"model": self.model, "input": batch, "truncate": False})
            vectors = response.get("embeddings")
            if not isinstance(vectors, list) or len(vectors) != len(batch):
                raise RuntimeError(f"Ollama embedding count mismatch at input offset {offset}")
            for vector in vectors:
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("Ollama returned an empty embedding")
                norm = math.sqrt(sum(float(value) * float(value) for value in vector))
                if not math.isfinite(norm) or norm == 0.0:
                    raise RuntimeError("Ollama returned an invalid zero/non-finite embedding")
                normalized = [float(value) / norm for value in vector]
                if self.dimension is not None and len(normalized) != self.dimension:
                    raise RuntimeError("Embedding dimension changed during the run")
                output.append(normalized)
        return output


def _required_evidence(question: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> dict[str, ResolvedGold]:
    chunk_ids = [str(item) for item in question["required_chunks"]]
    chunk_evidence: list[GoldEvidence] = []
    pages: set[tuple[str, int]] = {
        (str(item.get("document_id")), int(item["page"]))
        for item in question.get("required_pages") or [] if item.get("page") is not None
    }
    documents = {str(value) for value in question.get("required_documents") or []}
    for chunk_id in chunk_ids:
        row = corpus_by_id[chunk_id]
        document_id = str(row["document_id"])
        page_pairs = _row_pages(row)
        if not pages:
            pages.update(page_pairs)
        first_page = min((page for _, page in page_pairs), default=None)
        last_page = max((page for _, page in page_pairs), default=first_page)
        chunk_evidence.append(GoldEvidence(chunk_id, document_id, first_page, "required_evidence", last_page))
    qid = str(question["question_id"])
    by_page = tuple(GoldEvidence(f"page:{doc}:{page}", doc, page, "required_evidence", page)
                    for doc, page in sorted(pages))
    by_document = tuple(GoldEvidence(f"document:{doc}", doc, None, "required_evidence") for doc in sorted(documents))
    return {
        "chunk": ResolvedGold(qid, tuple(chunk_evidence), metadata={"benchmark_type": "silver"}),
        "page": ResolvedGold(qid, by_page, metadata={"benchmark_type": "silver"}),
        "document": ResolvedGold(qid, by_document, metadata={"benchmark_type": "silver"}),
    }


def _query_trace(question: dict[str, Any], hits: list[Any], required: ResolvedGold) -> list[dict[str, Any]]:
    required_chunks = {item.chunk_id for item in required.required}
    required_pages = {(item.document_id, page) for item in required.required if item.page is not None
                      for page in range(item.page, (item.page_end or item.page) + 1)}
    required_documents = {item.document_id for item in required.required}
    traces = []
    for hit in hits[:10]:
        hit_pages = {(hit.document_id, page) for page in range(hit.page, (hit.page_end or hit.page) + 1)} if hit.page is not None else set()
        traces.append({
            "question_id": question["question_id"], "question": question["question"],
            "species": question.get("species") or "unknown", "query_style": question.get("query_style"),
            "lexical_overlap": question.get("lexical_overlap"), "rank": hit.rank,
            "chunk_id": hit.chunk_id, "document_id": hit.document_id, "page": hit.page,
            "page_end": hit.page_end, "score": hit.raw_score, "raw_score": hit.raw_score,
            "is_required_evidence": hit.chunk_id in required_chunks,
            "chunk_match": hit.chunk_id in required_chunks,
            "page_match": bool(hit_pages & required_pages),
            "document_match": hit.document_id in required_documents,
            "mapping_status": "exact_by_construction",
        })
    return traces


def _evidence_coverage(hits: list[Any], question: dict[str, Any]) -> dict[str, Any]:
    required_chunks = {str(value) for value in question.get("required_chunks") or []}
    required_pages = {(str(item.get("document_id")), int(item["page"])) for item in question.get("required_pages") or []}
    required_docs = {str(value) for value in question.get("required_documents") or []}
    result: dict[str, Any] = {}
    for k in TOP_K:
        selected = hits[:k]
        hit_chunks = {hit.chunk_id for hit in selected}
        hit_pages = {(hit.document_id, page) for hit in selected if hit.page is not None
                     for page in range(hit.page, (hit.page_end or hit.page) + 1)}
        hit_docs = {hit.document_id for hit in selected}
        chunk_matches = required_chunks & hit_chunks
        page_matches = required_pages & hit_pages
        doc_matches = required_docs & hit_docs
        result[str(k)] = {
            "required_chunk_coverage": len(chunk_matches) / len(required_chunks) if required_chunks else None,
            "required_page_coverage": len(page_matches) / len(required_pages) if required_pages else None,
            "required_document_coverage": len(doc_matches) / len(required_docs) if required_docs else None,
            "required_chunk_hit": bool(chunk_matches),
            "all_required_chunks": bool(required_chunks) and required_chunks.issubset(hit_chunks),
            "all_required_pages": bool(required_pages) and required_pages.issubset(hit_pages),
            "all_required_documents": bool(required_docs) and required_docs.issubset(hit_docs),
        }
    return result


def _error_candidate(question: dict[str, Any], hits: list[Any], full_hits: list[Any]) -> dict[str, Any]:
    required_chunks = {str(value) for value in question.get("required_chunks") or []}
    required_docs = {str(value) for value in question.get("required_documents") or []}
    required_pages = {(str(item.get("document_id")), int(item["page"])) for item in question.get("required_pages") or []}
    top_chunks = {hit.chunk_id for hit in hits[:10]}
    top_docs = {hit.document_id for hit in hits[:10]}
    top_pages = {(hit.document_id, page) for hit in hits[:10] if hit.page is not None
                 for page in range(hit.page, (hit.page_end or hit.page) + 1)}
    rank_by_chunk = {hit.chunk_id: hit.rank for hit in full_hits}
    matched_docs = top_docs & required_docs
    matched_pages = top_pages & required_pages
    missing_required = sorted(required_chunks - top_chunks)
    if not missing_required:
        category = None
    elif len(required_docs) > 1 and matched_docs and not required_docs.issubset(top_docs):
        category = "multi_document_partial"
    elif matched_docs and not matched_pages:
        category = "correct_document_wrong_page"
    elif matched_pages:
        category = "correct_page_wrong_chunk"
    else:
        closest_required_rank = min((rank_by_chunk.get(chunk, 10**9) for chunk in required_chunks), default=10**9)
        if closest_required_rank <= 50:
            category = "relevant_below_k"
        elif hits and not matched_docs:
            category = "wrong_document"
        elif hits:
            category = "no_relevant_retrieved"
        else:
            category = "no_relevant_retrieved"
    if category is None:
        reason = "all_required_chunks_retrieved_at_top10"
    else:
        reason = "automatic_candidate_requires_manual_interpretation"
    return {"question_id": question["question_id"], "error_category": category, "candidate_reason": reason,
            "missing_required_chunks": missing_required,
            "required_chunk_ranks_full": {chunk: rank_by_chunk.get(chunk) for chunk in sorted(required_chunks)},
            "classification_confidence": "candidate" if category else "none",
            "taxonomy": list(ERROR_TAXONOMY)}


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"question_count": 0, "metrics": {}}
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    evidence: dict[str, list[float]] = defaultdict(list)
    successes: Counter[str] = Counter()
    for row in rows:
        for granularity, metric_row in row["metrics"].items():
            for name, value in metric_row.items():
                values[granularity][name].append(float(value))
        for k, result in row["required_evidence_coverage"].items():
            evidence[f"required_chunk_coverage@{k}"].append(float(result["required_chunk_coverage"] or 0.0))
            successes[f"all_required_chunks@{k}"] += bool(result["all_required_chunks"])
            successes[f"all_required_pages@{k}"] += bool(result["all_required_pages"])
            successes[f"all_required_documents@{k}"] += bool(result["all_required_documents"])
    return {
        "question_count": len(rows),
        "metrics": {gran: {name: sum(series) / len(series) for name, series in sorted(by_name.items()) if series}
                    for gran, by_name in sorted(values.items())},
        "required_evidence": {
            "mean_required_chunk_coverage": {name.rsplit("@", 1)[1]: sum(series) / len(series)
                                              for name, series in sorted(evidence.items()) if series},
            "success_counts": dict(sorted(successes.items())),
            "multi_document_questions": sum(bool(row["question"].get("multi_document")) for row in rows),
            "multi_document_all_required_success_top10": sum(
                bool(row["question"].get("multi_document")) and row["required_evidence_coverage"]["10"]["all_required_chunks"]
                for row in rows),
            "single_document_questions": sum(not bool(row["question"].get("multi_document")) for row in rows),
            "single_document_all_required_success_top10": sum(
                not bool(row["question"].get("multi_document")) and row["required_evidence_coverage"]["10"]["all_required_chunks"]
                for row in rows),
        },
    }


def _group_reports(rows: list[dict[str, Any]], *, field: str, expected_order: tuple[str, ...] | None = None) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row["question"].get(field)
        key = str(value) if value not in (None, "") else "unknown"
        grouped[key].append(row)
    if expected_order:
        for key in expected_order:
            grouped.setdefault(key, [])
    return {key: _summarize_rows(grouped[key]) for key in sorted(grouped)}


def _write_experiment_reports(
    directory: Path,
    *,
    experiment_id: str,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "experiment_manifest.json", manifest)
    overall = _summarize_rows(rows)
    overall.update({"experiment_id": experiment_id, "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold"})
    write_json(directory / "overall.json", overall)
    write_json(directory / "by_query_style.json", _group_reports(rows, field="query_style"))
    overlap = {}
    for bucket, (lower, upper) in OVERLAP_BUCKETS.items():
        chosen = []
        for row in rows:
            score = float(row["question"].get("lexical_overlap") or 0.0)
            if lexical_overlap_bucket(score) == bucket:
                chosen.append(row)
        overlap[bucket] = _summarize_rows(chosen)
    write_json(directory / "by_overlap.json", {"boundaries": {"low": "<0.35", "medium": "0.35 through 0.55", "high": ">0.55"}, "groups": overlap})
    write_json(directory / "by_species.json", _group_reports(rows, field="species", expected_order=SPECIES_REPORT_ORDER))
    write_json(directory / "by_category.json", _group_reports(rows, field="category", expected_order=CATEGORY_REPORT_ORDER))
    write_json(directory / "by_difficulty.json", _group_reports(rows, field="difficulty"))
    write_jsonl(directory / "per_question.jsonl", rows)
    write_jsonl(directory / "ranking_traces.jsonl", traces)
    write_jsonl(directory / "errors.jsonl", errors)


def lexical_overlap_bucket(score: float) -> str:
    if score < 0.35:
        return "low"
    if score <= 0.55:
        return "medium"
    return "high"


def run_retriever(
    *,
    experiment_id: str,
    retriever: Any,
    questions: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    corpus_sha256: str,
    question_sha256: str,
    evidence_pool_sha256: str,
    evidence_resolution_sha256: str,
    git_commit: str,
    timestamp: str,
    output_directory: Path,
    retriever_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus}
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    all_full_rankings: dict[str, list[Any]] = {}
    top_k_hash_parts: list[dict[str, Any]] = []
    for question in questions:
        full_hits = retriever.rank_all(str(question["question"]))
        if len(full_hits) != len(corpus):
            raise RuntimeError(f"Retriever did not rank the complete frozen corpus for {question['question_id']}")
        if len({hit.chunk_id for hit in full_hits}) != len(corpus_by_id):
            raise RuntimeError(f"Retriever ranking has missing/duplicate chunk ids for {question['question_id']}")
        all_full_rankings[str(question["question_id"])] = full_hits
        hits = full_hits[:10]
        evidence = _required_evidence(question, corpus_by_id)
        result = RetrievalResult(str(question["question_id"]), tuple(hits))
        metrics = {granularity: metric_bundle(result, evidence[granularity], granularity).scores
                   for granularity in GRANULARITIES}
        qrow = {
            "question_id": question["question_id"],
            "question": question,
            "metrics": metrics,
            "required_evidence_coverage": _evidence_coverage(full_hits, question),
            "retrieval_top10_chunk_ids": [hit.chunk_id for hit in hits],
        }
        rows.append(qrow)
        traces.extend(_query_trace(question, hits, evidence["chunk"]))
        error = _error_candidate(question, hits, full_hits)
        if error.get("error_category"):
            errors.append(error)
        top_k_hash_parts.append({"question_id": question["question_id"], "top10": [hit.chunk_id for hit in hits]})
    manifest = {
        "experiment_id": experiment_id,
        "status": "completed",
        "timestamp": timestamp,
        "evaluation_corpus_v2_sha256": corpus_sha256,
        "grounded_questions_v1_sha256": question_sha256,
        "evidence_pool_v1_sha256": evidence_pool_sha256,
        "required_evidence_resolution_sha256": evidence_resolution_sha256,
        "required_evidence_definition": "Grounded Silver required_chunks/pages/documents; not human Gold",
        "question_count": len(questions),
        "question_ids_sha256": stable_sha256(sorted(str(q["question_id"]) for q in questions)),
        "retrieval_corpus_chunk_ids_sha256": stable_sha256(sorted(str(row["chunk_id"]) for row in corpus)),
        "retrieval_chunk_count": len(corpus),
        "top_k": list(TOP_K),
        "metric_implementation": "src.evaluation.retrieval.metrics.metric_bundle",
        "metric_semantics": "top-K ranks retrieved chunks; each chunk contributes at most one Precision/nDCG gain at page/document granularity, while Recall counts unique matched evidence units",
        "granularities": list(GRANULARITIES),
        "retriever_type": retriever.retriever_type,
        "retriever_config": retriever_config or retriever.index_manifest,
        "git_commit": git_commit,
        "ranking_determinism": "fixed corpus order, fixed model vectors, score-descending/chunk_id-ascending tie break",
        "ranking_trace_count": len(traces),
        "top10_rankings_sha256": stable_sha256(top_k_hash_parts),
        "gold_evidence_used_for_ranking": False,
        "metadata_filter_used": False,
    }
    _write_experiment_reports(output_directory, experiment_id=experiment_id, manifest=manifest,
                              rows=rows, traces=traces, errors=errors)
    write_json(output_directory / "ranking_validation.json", {
        "all_questions_have_trace": len({row["question_id"] for row in traces}) == len(questions),
        "trace_rows_expected": len(questions) * 10,
        "trace_rows_actual": len(traces),
        "every_question_full_ranked": len(all_full_rankings) == len(questions),
        "ranking_top10_sha256": manifest["top10_rankings_sha256"],
        "error_taxonomy_counts": dict(Counter(row["error_category"] for row in errors)),
    })
    return {"manifest": manifest, "rows": rows, "traces": traces, "errors": errors, "full_rankings": all_full_rankings}


def _bootstrap_percentiles(values: list[float], *, seed: int, iterations: int) -> dict[str, Any]:
    # NumPy is intentionally not a dependency: use one seeded RNG stream for repeatable resampling.
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(iterations):
        samples.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    samples.sort()
    low_index = max(0, int(0.025 * (iterations - 1)))
    high_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return {"lower_95": samples[low_index], "upper_95": samples[high_index]}


def bootstrap_comparison(e1_rows: list[dict[str, Any]], e2_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if [row["question_id"] for row in e1_rows] != [row["question_id"] for row in e2_rows]:
        raise ValueError("Paired bootstrap requires identical ordered question IDs")
    groups: dict[str, Any] = {}
    for granularity in GRANULARITIES:
        groups[granularity] = {}
        for metric in BOOTSTRAP_METRICS:
            e1_values = [float(row["metrics"][granularity][metric]) for row in e1_rows]
            e2_values = [float(row["metrics"][granularity][metric]) for row in e2_rows]
            # Same resampled question positions for E1/E2 provides a paired interval.
            rng = random.Random(BOOTSTRAP_SEED)
            n = len(e1_values)
            e1_samples: list[float] = []
            e2_samples: list[float] = []
            delta_samples: list[float] = []
            for _ in range(BOOTSTRAP_ITERATIONS):
                indices = [rng.randrange(n) for _ in range(n)]
                left = sum(e1_values[index] for index in indices) / n
                right = sum(e2_values[index] for index in indices) / n
                e1_samples.append(left)
                e2_samples.append(right)
                delta_samples.append(right - left)
            def ci(samples: list[float]) -> dict[str, float]:
                samples.sort()
                return {"lower_95": samples[int(0.025 * (BOOTSTRAP_ITERATIONS - 1))],
                        "upper_95": samples[int(0.975 * (BOOTSTRAP_ITERATIONS - 1))]}
            groups[granularity][metric] = {
                "E1": ci(e1_samples), "E2": ci(e2_samples), "E2_minus_E1_paired": ci(delta_samples),
                "delta_point_estimate": sum(e2_values) / n - sum(e1_values) / n,
            }
    return {
        "method": "paired percentile bootstrap over questions with replacement",
        "confidence_level": 0.95,
        "random_seed": BOOTSTRAP_SEED,
        "iterations": BOOTSTRAP_ITERATIONS,
        "sample_unit": "question_id",
        "interpretation_limit": "CI describes uncertainty on this AI-generated Silver benchmark sample only; it does not establish performance over all aquaculture questions.",
        "metrics": groups,
    }


def paired_comparison(e1: dict[str, Any], e2: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    e1_by_id = {row["question_id"]: row for row in e1["rows"]}
    e2_by_id = {row["question_id"]: row for row in e2["rows"]}
    if set(e1_by_id) != set(e2_by_id):
        raise ValueError("E1/E2 question ID sets differ")
    e1_positions = e1["full_rankings"]
    e2_positions = e2["full_rankings"]
    per_question: list[dict[str, Any]] = []
    paired_rank: list[dict[str, Any]] = []
    categories = {k: Counter() for k in TOP_K}
    for qid in sorted(e1_by_id):
        row1, row2 = e1_by_id[qid], e2_by_id[qid]
        question = row1["question"]
        required = {str(value) for value in question.get("required_chunks") or []}
        ranks1 = {hit.chunk_id: hit.rank for hit in e1_positions[qid]}
        ranks2 = {hit.chunk_id: hit.rank for hit in e2_positions[qid]}
        first1 = min((ranks1.get(chunk, 10**9) for chunk in required), default=10**9)
        first2 = min((ranks2.get(chunk, 10**9) for chunk in required), default=10**9)
        hit_data = {}
        for k in (1, 5, 10):
            h1 = any(ranks1.get(chunk, 10**9) <= k for chunk in required)
            h2 = any(ranks2.get(chunk, 10**9) <= k for chunk in required)
            label = "both_hit" if h1 and h2 else "bm25_only_hit" if h1 else "dense_only_hit" if h2 else "both_miss"
            categories[k][label] += 1
            hit_data[str(k)] = {"bm25_hit": h1, "dense_hit": h2, "paired_category": label}
        def top10_rank(value: int) -> int | None:
            return value if value <= 10 else None
        e1_rank, e2_rank = top10_rank(first1), top10_rank(first2)
        rank_delta = e2_rank - e1_rank if e1_rank is not None and e2_rank is not None else None
        base = {
            "question_id": qid, "question": question["question"], "species": question.get("species") or "unknown",
            "query_style": question.get("query_style"), "lexical_overlap": question.get("lexical_overlap"),
            "hits": hit_data,
        }
        per_question.append(base)
        paired_rank.append({**base,
            "bm25_first_required_evidence_rank_top10": e1_rank,
            "dense_first_required_evidence_rank_top10": e2_rank,
            "bm25_rank_status": "hit_top10" if e1_rank is not None else "missed_top10",
            "dense_rank_status": "hit_top10" if e2_rank is not None else "missed_top10",
            "rank_difference_dense_minus_bm25": rank_delta,
            "rank_difference_note": "null when either required evidence item was outside Top 10; missing ranks are not encoded as 11",
            "bm25_first_required_evidence_rank_full": first1 if first1 < 10**9 else None,
            "dense_first_required_evidence_rank_full": first2 if first2 < 10**9 else None,
        })
    summary = {f"hit@{k}": {key: categories[k].get(key, 0) for key in ("bm25_only_hit", "dense_only_hit", "both_hit", "both_miss")}
               for k in (1, 5, 10)}
    summary["paired_question_count"] = len(per_question)
    summary["complementarity_at_10"] = {
        "bm25_only_required_evidence_hits": categories[10].get("bm25_only_hit", 0),
        "dense_only_required_evidence_hits": categories[10].get("dense_only_hit", 0),
        "both_retrievers_have_unique_hits": bool(categories[10].get("bm25_only_hit", 0) and categories[10].get("dense_only_hit", 0)),
    }
    delta_values = [row["rank_difference_dense_minus_bm25"] for row in paired_rank if row["rank_difference_dense_minus_bm25"] is not None]
    summary["rank_difference_top10"] = {
        "paired_rank_count": len(delta_values),
        "mean_dense_minus_bm25": sum(delta_values) / len(delta_values) if delta_values else None,
        "median_dense_minus_bm25": sorted(delta_values)[len(delta_values) // 2] if delta_values else None,
    }
    return summary, per_question, paired_rank


def leakage_audit(questions: list[dict[str, Any]], corpus_by_id: dict[str, dict[str, Any]], *, suspicious_substring_length: int = 16) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_style: dict[str, list[int]] = defaultdict(list)
    for question in questions:
        normalized_question = "".join(ch for ch in str(question.get("question") or "").casefold() if ch.isalnum() or "\u3400" <= ch <= "\u9fff")
        best: tuple[int, str, str] = (0, "", "")
        for chunk_id in question.get("required_chunks") or []:
            evidence = corpus_by_id[str(chunk_id)]
            normalized_evidence = "".join(ch for ch in str(evidence.get("text") or "").casefold() if ch.isalnum() or "\u3400" <= ch <= "\u9fff")
            match = difflib.SequenceMatcher(None, normalized_question, normalized_evidence, autojunk=False).find_longest_match()
            candidate = normalized_question[match.a:match.a + match.size]
            if match.size > best[0]:
                best = (match.size, candidate, str(chunk_id))
        style = str(question.get("query_style") or "unknown")
        by_style[style].append(best[0])
        rows.append({
            "question_id": question["question_id"], "query_style": style,
            "lexical_overlap": question.get("lexical_overlap"),
            "longest_exact_normalized_substring_chars": best[0],
            "longest_substring": best[1], "required_chunk_id": best[2] or None,
            "suspicious_long_substring": best[0] >= suspicious_substring_length,
        })
    lengths = [row["longest_exact_normalized_substring_chars"] for row in rows]
    return {
        "method": "longest contiguous exact substring after deterministic punctuation/space normalization",
        "suspicious_substring_threshold_chars": suspicious_substring_length,
        "direct_questions_are_retained": True,
        "question_count": len(rows),
        "suspicious_question_count": sum(row["suspicious_long_substring"] for row in rows),
        "longest_substring_length": max(lengths, default=0),
        "mean_longest_substring_length": sum(lengths) / len(lengths) if lengths else None,
        "by_query_style": {style: {"question_count": len(values), "suspicious_question_count": sum(value >= suspicious_substring_length for value in values),
                                    "mean_longest_substring_length": sum(values) / len(values) if values else None,
                                    "max_longest_substring_length": max(values, default=0)}
                           for style, values in sorted(by_style.items())},
        "rows": rows,
        "interpretation": "Flags describe lexical overlap risk in an evidence-generated Silver set; they are not grounds to remove Direct questions or claims of answer correctness.",
    }


def error_comparison(e1: list[dict[str, Any]], e2: list[dict[str, Any]], paired_rows: list[dict[str, Any]]) -> dict[str, Any]:
    e1_errors = {row["question_id"]: row["error_category"] for row in e1}
    e2_errors = {row["question_id"]: row["error_category"] for row in e2}
    e1_only = e2_only = both = neither = 0
    question_error_rows = []
    by_style: dict[str, Counter[str]] = defaultdict(Counter)
    by_overlap: dict[str, Counter[str]] = defaultdict(Counter)
    for row in paired_rows:
        qid = row["question_id"]
        a, b = e1_errors.get(qid), e2_errors.get(qid)
        if a and b:
            both += 1
            bucket = "both_fail"
        elif a:
            e1_only += 1
            bucket = "bm25_failure_only"
        elif b:
            e2_only += 1
            bucket = "dense_failure_only"
        else:
            neither += 1
            bucket = "neither_fail"
        by_style[str(row.get("query_style") or "unknown")][bucket] += 1
        by_overlap[lexical_overlap_bucket(float(row.get("lexical_overlap") or 0.0))][bucket] += 1
        question_error_rows.append({"question_id": qid, "paired_failure_group": bucket,
                                    "bm25_candidate_error": a, "dense_candidate_error": b})
    def full_taxonomy(values: Counter[str]) -> dict[str, int]:
        return {name: values.get(name, 0) for name in ERROR_TAXONOMY}
    return {
        "taxonomy": list(ERROR_TAXONOMY),
        "E1_error_distribution": full_taxonomy(Counter(e1_errors.values())),
        "E2_error_distribution": full_taxonomy(Counter(e2_errors.values())),
        "paired_failure_groups": {"bm25_failure_only": e1_only, "dense_failure_only": e2_only,
                                  "both_fail": both, "neither_fail": neither},
        "paired_failure_groups_by_query_style": {key: dict(value) for key, value in sorted(by_style.items())},
        "paired_failure_groups_by_overlap_bucket": {key: dict(value) for key, value in sorted(by_overlap.items())},
        "automatic_error_rows": question_error_rows,
        "interpretation": "Automatic taxonomy entries are candidates based on ranking traces; unclear cases remain unknown and should be manually reviewed before causal claims.",
    }


def fairness_validation(e1: dict[str, Any], e2: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    e1_ids = sorted(row["question_id"] for row in e1["rows"])
    e2_ids = sorted(row["question_id"] for row in e2["rows"])
    e1_chunks = e1["manifest"]["retrieval_corpus_chunk_ids_sha256"]
    e2_chunks = e2["manifest"]["retrieval_corpus_chunk_ids_sha256"]
    e1_evidence = e1["manifest"]["required_evidence_resolution_sha256"]
    e2_evidence = e2["manifest"]["required_evidence_resolution_sha256"]
    checks = {
        "same_question_ids": e1_ids == e2_ids,
        "same_retrieval_corpus_chunk_ids": e1_chunks == e2_chunks == frozen["corpus_chunk_ids_sha256"],
        "same_top_k": e1["manifest"]["top_k"] == e2["manifest"]["top_k"] == list(TOP_K),
        "same_metric_implementation": e1["manifest"]["metric_implementation"] == e2["manifest"]["metric_implementation"],
        "same_required_evidence": e1_evidence == e2_evidence == frozen["evidence_resolution_sha256"],
        "no_gold_evidence_used_for_ranking": not e1["manifest"]["gold_evidence_used_for_ranking"] and not e2["manifest"]["gold_evidence_used_for_ranking"],
        "same_question_count": len(e1_ids) == len(e2_ids) == len(frozen["questions"]),
    }
    if not all(checks.values()):
        raise RuntimeError(f"E1/E2 fairness check failed: {checks}")
    return {"status": "passed", "checks": checks, "question_count": len(e1_ids),
            "retrieval_chunk_count": len(frozen["corpus"]),
            "required_evidence_resolution_sha256": e1_evidence}


def protected_file_snapshot(root: Path) -> dict[str, Any]:
    relative_paths = (
        "rag_store.sqlite3", "data/shadow/chunks_v2.jsonl", "data/shadow/chunks_v3.jsonl",
        "data/evaluation/corpus_v1.jsonl", "data/evaluation/corpus_v2.jsonl",
        "data/evaluation/silver/questions_v1.jsonl", "data/evaluation/silver/questions_v2.jsonl",
        "data/evaluation/silver/questions_v3.jsonl", "data/evaluation/grounded/questions_v1.jsonl",
        "data/evaluation/grounded/evidence_pool_v1.jsonl",
    )
    output = {}
    for relative in relative_paths:
        path = root / relative
        if path.is_file():
            stat = path.stat()
            output[relative] = {"sha256": sha256_file(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        else:
            output[relative] = {"status": "missing"}
    return output


def verify_protected_snapshot(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes = {key: {"before": before.get(key), "after": after.get(key)}
               for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}
    return {"status": "passed" if not changes else "failed", "changed_files": changes,
            "protected_file_count": len(before)}


def dense_preflight_failure(directory: Path, *, timestamp: str, frozen: dict[str, Any], git_commit: str,
                           error: str) -> dict[str, Any]:
    manifest = {
        "experiment_id": "E2_grounded_dense_v1", "status": "blocked_runtime", "timestamp": timestamp,
        "evaluation_corpus_v2_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "grounded_questions_v1_sha256": frozen["hashes"]["grounded_questions_v1"],
        "evidence_pool_v1_sha256": frozen["hashes"]["evidence_pool_v1"],
        "question_count": len(frozen["questions"]), "model_requested": "bge-m3:latest",
        "runtime_error": error, "git_commit": git_commit,
        "note": "No replacement model was selected; E1 completed independently.",
    }
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "experiment_manifest.json", manifest)
    write_json(directory / "overall.json", {"status": "blocked_runtime", "results": None, "runtime_error": error})
    for name in ("by_query_style.json", "by_overlap.json", "by_species.json", "by_category.json", "by_difficulty.json"):
        write_json(directory / name, {"status": "blocked_runtime", "results": None})
    for name in ("per_question.jsonl", "ranking_traces.jsonl", "errors.jsonl"):
        write_jsonl(directory / name, [])
    return manifest


def _write_f32(path: Path, vectors: list[list[float]]) -> None:
    from array import array
    if array("f").itemsize != 4:
        raise RuntimeError("Host float array is not IEEE-sized 32-bit; cannot write the declared vector format")
    temp_path = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as stream:
        for vector in vectors:
            values = array("f", vector)
            if values.itemsize != 4:
                raise RuntimeError("Unexpected float32 storage width")
            if __import__("sys").byteorder != "little":
                values.byteswap()
            values.tofile(stream)
    temp_path.replace(path)


def _read_f32(path: Path, *, count: int, dimension: int) -> list[list[float]]:
    from array import array
    import sys
    values = array("f")
    with path.open("rb") as stream:
        values.fromfile(stream, count * dimension)
        if stream.read(1):
            raise RuntimeError(f"Float32 vector file has trailing bytes: {path}")
    if len(values) != count * dimension:
        raise RuntimeError(f"Float32 vector count mismatch: {path}")
    if sys.byteorder != "little":
        values.byteswap()
    return [values[offset:offset + dimension].tolist() for offset in range(0, len(values), dimension)]


def build_dense_index(root: Path, frozen: dict[str, Any], runtime: OllamaEmbeddingRuntime,
                      runtime_metadata: dict[str, Any], git_commit: str, timestamp: str) -> tuple[EvaluationDense, dict[str, Any]]:
    index_directory = root / "data/evaluation/indexes/E2_grounded_bge_m3_v1"
    index_directory.mkdir(parents=True, exist_ok=True)
    corpus = frozen["corpus"]
    texts = [str(row.get("text") or "") for row in corpus]
    vectors = runtime.embed_texts(texts, batch_size=32)
    if len(vectors) != len(corpus):
        raise RuntimeError("Dense embedding count does not equal frozen retrieval corpus count")
    dimension = int(runtime.dimension or 0)
    if not dimension or any(len(vector) != dimension for vector in vectors):
        raise RuntimeError("Dense corpus embeddings do not have the preflight dimension")
    vector_path = index_directory / "vectors.f32"
    _write_f32(vector_path, vectors)
    chunk_rows = []
    for row in corpus:
        pages = sorted(page for _, page in _row_pages(row))
        chunk_rows.append({"chunk_id": row["chunk_id"], "document_id": row["document_id"],
                           "pages": pages, "content_checksum": row.get("content_checksum")})
    write_jsonl(index_directory / "chunks.jsonl", chunk_rows)
    queries = frozen["questions"]
    query_texts = [str(row["question"]) for row in queries]
    query_vectors = runtime.embed_texts(query_texts, batch_size=32)
    if len(query_vectors) != len(queries) or any(len(vector) != dimension for vector in query_vectors):
        raise RuntimeError("Dense query embeddings do not match frozen question count/dimension")
    query_vector_path = index_directory / "query_vectors.f32"
    _write_f32(query_vector_path, query_vectors)
    write_jsonl(index_directory / "queries.jsonl", [
        {"question_id": row["question_id"], "query_sha256": hashlib.sha256(str(row["question"]).encode("utf-8")).hexdigest()}
        for row in queries
    ])
    manifest = {
        "index_id": "E2_grounded_bge_m3_v1",
        "index_type": "evaluation_only_dense_float32",
        "corpus_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "retrieval_chunk_count": len(corpus),
        "corpus_chunk_ids_sha256": frozen["corpus_chunk_ids_sha256"],
        "document_count": frozen["corpus_profile"]["document_count"],
        "page_count": frozen["corpus_profile"]["page_count"],
        "created_at": timestamp,
        "git_commit": git_commit,
        "model": runtime_metadata,
        "embedding_dimension": dimension,
        "normalization": "L2 unit normalization applied independently before float32 serialization; ranking reloads the exact persisted float32 vectors",
        "distance_metric": "cosine similarity via dot product on normalized float32 vectors",
        "vector_dtype": "IEEE 754 float32 little-endian",
        "query_count": len(queries),
        "vectors_file": vector_path.name,
        "vectors_sha256": sha256_file(vector_path),
        "query_vectors_file": query_vector_path.name,
        "query_vectors_sha256": sha256_file(query_vector_path),
        "chunks_file": "chunks.jsonl",
        "chunks_sha256": sha256_file(index_directory / "chunks.jsonl"),
        "query_map_file": "queries.jsonl",
        "query_map_sha256": sha256_file(index_directory / "queries.jsonl"),
        "uses_production_vectors": False,
        "uses_expected_evidence_for_index_or_ranking": False,
        "context_only_excluded": True,
        "noncanonical_duplicate_excluded": True,
    }
    write_json(index_directory / "index_manifest.json", manifest)
    # Rank from the serialized representation so every result corresponds exactly
    # to the persistent evaluation-only index, rather than transient API doubles.
    stored_vectors = _read_f32(vector_path, count=len(corpus), dimension=dimension)
    stored_query_vectors = _read_f32(query_vector_path, count=len(queries), dimension=dimension)
    query_map = {str(row["question"]): vector for row, vector in zip(queries, stored_query_vectors)}
    retriever = EvaluationDense(corpus, stored_vectors, query_map, manifest=manifest)
    return retriever, manifest


def load_dense_index(root: str | Path, frozen: dict[str, Any]) -> tuple[EvaluationDense, dict[str, Any]]:
    """Load and validate the exact persisted float32 index and frozen query vectors."""
    index_directory = Path(root) / "data/evaluation/indexes/E2_grounded_bge_m3_v1"
    manifest = json.loads((index_directory / "index_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("corpus_sha256") != frozen["hashes"]["evaluation_corpus_v2"]:
        raise RuntimeError("Saved Dense index corpus checksum does not match the frozen corpus")
    if manifest.get("retrieval_chunk_count") != len(frozen["corpus"]):
        raise RuntimeError("Saved Dense index chunk count does not match the frozen corpus")
    if sha256_file(index_directory / manifest["vectors_file"]) != manifest.get("vectors_sha256"):
        raise RuntimeError("Saved Dense corpus vectors checksum mismatch")
    if sha256_file(index_directory / manifest["query_vectors_file"]) != manifest.get("query_vectors_sha256"):
        raise RuntimeError("Saved Dense query vectors checksum mismatch")
    chunk_rows = read_jsonl(index_directory / manifest["chunks_file"])
    if [str(row.get("chunk_id")) for row in chunk_rows] != [str(row.get("chunk_id")) for row in frozen["corpus"]]:
        raise RuntimeError("Saved Dense index chunk IDs/order differ from frozen corpus")
    query_rows = read_jsonl(index_directory / manifest["query_map_file"])
    if [str(row.get("question_id")) for row in query_rows] != [str(row.get("question_id")) for row in frozen["questions"]]:
        raise RuntimeError("Saved Dense query IDs/order differ from frozen Grounded Silver")
    for row, query_row in zip(query_rows, frozen["questions"]):
        query_sha = hashlib.sha256(str(query_row["question"]).encode("utf-8")).hexdigest()
        if row.get("query_sha256") != query_sha:
            raise RuntimeError(f"Saved Dense query map changed for {query_row['question_id']}")
    dimension = int(manifest["embedding_dimension"])
    vectors = _read_f32(index_directory / manifest["vectors_file"], count=len(frozen["corpus"]), dimension=dimension)
    query_vectors = _read_f32(index_directory / manifest["query_vectors_file"], count=len(frozen["questions"]), dimension=dimension)
    query_map = {str(question["question"]): vector for question, vector in zip(frozen["questions"], query_vectors)}
    return EvaluationDense(frozen["corpus"], vectors, query_map, manifest=manifest), manifest


def _determinism_check(retriever: Any, questions: list[dict[str, Any]], *, sample_count: int | None = None) -> dict[str, Any]:
    checked = questions if sample_count is None else questions[:sample_count]
    mismatches = []
    for question in checked:
        first = [hit.chunk_id for hit in retriever.retrieve(str(question["question"]), top_k=10)]
        second = [hit.chunk_id for hit in retriever.retrieve(str(question["question"]), top_k=10)]
        if first != second:
            mismatches.append(question["question_id"])
    return {"status": "passed" if not mismatches else "failed", "checked_questions": len(checked),
            "ranking_mismatch_question_ids": mismatches,
            "scope": "repeat ranking over the same frozen index and query vector; does not re-embed the corpus"}


def validate_metric_recompute(directory: Path, questions: list[dict[str, Any]], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    from .retrieval.models import RankedHit
    per_question = {row["question_id"]: row for row in read_jsonl(directory / "per_question.jsonl")}
    traces_by_qid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in read_jsonl(directory / "ranking_traces.jsonl"):
        traces_by_qid[str(trace["question_id"])].append(trace)
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus}
    mismatches = []
    for question in questions:
        qid = str(question["question_id"])
        traces = sorted(traces_by_qid.get(qid, []), key=lambda row: row["rank"])
        hits = tuple(RankedHit(rank=int(row["rank"]), chunk_id=str(row["chunk_id"]),
                               document_id=str(row["document_id"]), page=row.get("page"),
                               page_end=row.get("page_end"), raw_score=row.get("score")) for row in traces)
        result = RetrievalResult(qid, hits)
        evidence = _required_evidence(question, corpus_by_id)
        expected = {gran: metric_bundle(result, evidence[gran], gran).scores for gran in GRANULARITIES}
        saved = (per_question.get(qid) or {}).get("metrics") or {}
        for granularity in GRANULARITIES:
            for metric, value in expected[granularity].items():
                if abs(float(saved.get(granularity, {}).get(metric, float("nan"))) - float(value)) > 1e-12:
                    mismatches.append({"question_id": qid, "granularity": granularity, "metric": metric})
    result = {"status": "passed" if not mismatches else "failed", "question_count": len(questions),
              "recomputed_metric_count": len(questions) * len(GRANULARITIES) * (4 + 4 + 1 + 4),
              "mismatch_count": len(mismatches), "mismatches": mismatches[:20]}
    write_json(directory / "metric_recompute_validation.json", result)
    return result


def refresh_saved_metrics(root: str | Path) -> dict[str, Any]:
    """Recompute metrics/reports from already frozen Top-10 traces; never reranks."""
    root = Path(root).resolve()
    frozen = validate_frozen_inputs(root)
    experiments = root / "reports/evaluation/experiments"
    experiment_rows: dict[str, list[dict[str, Any]]] = {}
    for experiment_id in ("E1_grounded_bm25_v1", "E2_grounded_dense_v1"):
        directory = experiments / experiment_id
        old_rows = {row["question_id"]: row for row in read_jsonl(directory / "per_question.jsonl")}
        traces_by_qid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trace in read_jsonl(directory / "ranking_traces.jsonl"):
            traces_by_qid[str(trace["question_id"])].append(trace)
        corpus_by_id = {str(row["chunk_id"]): row for row in frozen["corpus"]}
        refreshed: list[dict[str, Any]] = []
        for question in frozen["questions"]:
            qid = str(question["question_id"])
            old = old_rows.get(qid)
            traces = sorted(traces_by_qid.get(qid, []), key=lambda row: int(row["rank"]))
            if old is None or len(traces) != 10:
                raise RuntimeError(f"Cannot refresh metrics without a complete saved Top-10 trace: {experiment_id} {qid}")
            from .retrieval.models import RankedHit
            hits = tuple(RankedHit(rank=int(item["rank"]), chunk_id=str(item["chunk_id"]),
                                   document_id=str(item["document_id"]), page=item.get("page"),
                                   page_end=item.get("page_end"), raw_score=item.get("score")) for item in traces)
            result = RetrievalResult(qid, hits)
            evidence = _required_evidence(question, corpus_by_id)
            metrics = {granularity: metric_bundle(result, evidence[granularity], granularity).scores
                       for granularity in GRANULARITIES}
            refreshed.append({**old, "metrics": metrics,
                              "required_evidence_coverage": _evidence_coverage(list(hits), question)})
        manifest = json.loads((directory / "experiment_manifest.json").read_text(encoding="utf-8"))
        manifest["metric_semantics"] = "top-K ranks retrieved chunks; each chunk contributes at most one Precision/nDCG gain at page/document granularity, while Recall counts unique matched evidence units"
        traces = [{**trace, "raw_score": trace.get("raw_score", trace.get("score"))}
                  for trace in read_jsonl(directory / "ranking_traces.jsonl")]
        errors = read_jsonl(directory / "errors.jsonl")
        _write_experiment_reports(directory, experiment_id=experiment_id, manifest=manifest,
                                  rows=refreshed, traces=traces, errors=errors)
        experiment_rows[experiment_id] = refreshed
        validation = validate_metric_recompute(directory, frozen["questions"], frozen["corpus"])
        if validation["status"] != "passed":
            raise RuntimeError(f"Metric recomputation from traces failed: {experiment_id}")

    compare_dir = experiments / "E1_vs_E2_grounded_v1"
    e1_rows = experiment_rows["E1_grounded_bm25_v1"]
    e2_rows = experiment_rows["E2_grounded_dense_v1"]
    bootstrap = bootstrap_comparison(e1_rows, e2_rows)
    comparison = json.loads((compare_dir / "comparison.json").read_text(encoding="utf-8"))
    comparison["E1_overall"] = _summarize_rows(e1_rows)
    comparison["E2_overall"] = _summarize_rows(e2_rows)
    comparison["E2_minus_E1"] = _comparison_metrics(e1_rows, e2_rows)
    comparison["metric_definition_revision"] = "one relevant retrieval result per ranked chunk; page/document precision and nDCG bounded by 1"
    write_json(compare_dir / "comparison.json", comparison)
    write_json(compare_dir / "bootstrap_ci.json", bootstrap)
    old_execution_path = compare_dir / "phase12_execution.json"
    if old_execution_path.is_file():
        execution = json.loads(old_execution_path.read_text(encoding="utf-8"))
        for key, experiment_id in (("E1", "E1_grounded_bm25_v1"), ("E2", "E2_grounded_dense_v1")):
            if key in execution:
                execution[key]["overall"] = _summarize_rows(experiment_rows[experiment_id])
        execution["bootstrap"] = bootstrap
        write_json(old_execution_path, execution)
    e1_manifest = json.loads((experiments / "E1_grounded_bm25_v1/experiment_manifest.json").read_text(encoding="utf-8"))
    e2_manifest = json.loads((experiments / "E2_grounded_dense_v1/experiment_manifest.json").read_text(encoding="utf-8"))
    paired_hits = json.loads((compare_dir / "paired_hits.json").read_text(encoding="utf-8"))
    runtime_metadata = e2_manifest["retriever_config"]["model"]
    leakage = json.loads((compare_dir / "leakage_audit.json").read_text(encoding="utf-8"))
    fairness = json.loads((compare_dir / "fairness_validation.json").read_text(encoding="utf-8"))
    frozen_for_summary = {**frozen, "corpus_profile": frozen["corpus_profile"]}
    summary = _summary_markdown(frozen=frozen_for_summary,
                                e1={"rows": e1_rows, "manifest": e1_manifest},
                                e2={"rows": e2_rows, "manifest": e2_manifest},
                                paired_hits=paired_hits, bootstrap=bootstrap, fairness=fairness,
                                runtime_metadata=runtime_metadata, leakage=leakage)
    (compare_dir / "comparison_summary.md").write_text(summary, encoding="utf-8", newline="\n")
    return {"status": "passed", "ranking_traces_reused": True,
            "ranking_changed": False, "E1_questions": len(e1_rows), "E2_questions": len(e2_rows),
            "metric_definition_revision": comparison["metric_definition_revision"],
            "comparison_directory": str(compare_dir)}


def _comparison_metrics(e1_rows: list[dict[str, Any]], e2_rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    by_id2 = {row["question_id"]: row for row in e2_rows}
    for granularity in GRANULARITIES:
        groups[granularity] = {}
        for metric in e1_rows[0]["metrics"][granularity]:
            values = [float(by_id2[row["question_id"]]["metrics"][granularity][metric]) -
                      float(row["metrics"][granularity][metric]) for row in e1_rows]
            groups[granularity][metric] = {
                "E2_minus_E1_mean": sum(values) / len(values),
                "E1_mean": sum(float(row["metrics"][granularity][metric]) for row in e1_rows) / len(e1_rows),
                "E2_mean": sum(float(by_id2[row["question_id"]]["metrics"][granularity][metric]) for row in e1_rows) / len(e1_rows),
            }
    return groups


def _summary_markdown(*, frozen: dict[str, Any], e1: dict[str, Any], e2: dict[str, Any],
                      paired_hits: dict[str, Any], bootstrap: dict[str, Any], fairness: dict[str, Any],
                      runtime_metadata: dict[str, Any], leakage: dict[str, Any]) -> str:
    lines = [
        "# E1 BM25 vs E2 Dense — Grounded Silver baseline",
        "",
        "This is a retrieval-only comparison on an AI-generated corpus-grounded Silver benchmark. It is not a human Gold accuracy result or a claim that reference answers are authoritative.",
        "",
        f"- Questions: {len(frozen['questions'])}",
        f"- Retrieval chunks: {len(frozen['corpus'])}; documents: {frozen['corpus_profile']['document_count']}; pages: {frozen['corpus_profile']['page_count']}",
        f"- Corpus SHA-256: `{frozen['hashes']['evaluation_corpus_v2']}`",
        f"- Questions SHA-256: `{frozen['hashes']['grounded_questions_v1']}`",
        f"- Evidence pool SHA-256: `{frozen['hashes']['evidence_pool_v1']}`",
        f"- Fairness validation: {fairness['status']}",
        f"- Dense model: `{runtime_metadata.get('model_tag')}` ({runtime_metadata.get('embedding_dimension')} dimensions), Ollama {runtime_metadata.get('runtime_version')}",
        "",
        "## Chunk retrieval summary",
        "",
        "| Metric | E1 BM25 | E2 Dense | E2 − E1 |",
        "|---|---:|---:|---:|",
    ]
    for metric in ("recall@1", "recall@5", "recall@10", "mrr", "ndcg@10"):
        value = _comparison_metrics(e1["rows"], e2["rows"])["chunk"][metric]
        lines.append(f"| {metric} | {value['E1_mean']:.4f} | {value['E2_mean']:.4f} | {value['E2_minus_E1_mean']:+.4f} |")
    lines.extend(["", "## Required evidence hits", "", "| Cutoff | BM25 only | Dense only | Both | Neither |", "|---|---:|---:|---:|---:|"])
    for k in (1, 5, 10):
        values = paired_hits[f"hit@{k}"]
        lines.append(f"| {k} | {values['bm25_only_hit']} | {values['dense_only_hit']} | {values['both_hit']} | {values['both_miss']} |")
    lines.extend([
        "", "## Uncertainty and limitations", "",
        f"Paired percentile bootstrap used {bootstrap['iterations']:,} resamples with seed {bootstrap['random_seed']}. Intervals describe this Silver sample only.",
        f"Lexical-overlap audit flagged {leakage['suspicious_question_count']} questions at or above {leakage['suspicious_substring_threshold_chars']} consecutive normalized characters; Direct questions remain included.",
        "The multi-document slice contains one question and calculation has three; those slices are descriptive only.虱目魚 has zero questions and is not assigned metrics.",
        "",
        "See the per-question results and Top-10 traces in the E1/E2 experiment directories. No RRF, reranker, answer generation, or answer evaluation ran in this phase.",
        "",
    ])
    return "\n".join(lines)


def run_phase12(root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve()
    reports_root = root / "reports/evaluation/experiments"
    e1_dir = reports_root / "E1_grounded_bm25_v1"
    e2_dir = reports_root / "E2_grounded_dense_v1"
    compare_dir = reports_root / "E1_vs_E2_grounded_v1"
    frozen_time = utc_now()
    protected_before = protected_file_snapshot(root)
    frozen = validate_frozen_inputs(root)
    git_commit = get_git_commit(root)
    freeze_report = {
        "timestamp": frozen_time, "git_commit": git_commit,
        "evaluation_corpus_v2_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "grounded_questions_v1_sha256": frozen["hashes"]["grounded_questions_v1"],
        "evidence_pool_v1_sha256": frozen["hashes"]["evidence_pool_v1"],
        "required_evidence_resolution_sha256": frozen["evidence_resolution_sha256"],
        "question_count": len(frozen["questions"]), "question_ids_sha256": frozen["question_ids_sha256"],
        "corpus_profile": frozen["corpus_profile"],
        "corpus_chunk_ids_sha256": frozen["corpus_chunk_ids_sha256"],
        "required_evidence_resolution_count": len(frozen["resolution"]),
        "required_evidence_resolution_failures": 0,
        "by_query_style": dict(Counter(str(row.get("query_style") or "unknown") for row in frozen["questions"])),
        "overlap_boundaries": {"low": "<0.35", "medium": "0.35 through 0.55", "high": ">0.55"},
        "top_k": list(TOP_K), "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "protected_files_at_start": protected_before,
    }
    write_json(e1_dir / "frozen_inputs.json", freeze_report)
    write_json(e2_dir / "frozen_inputs.json", freeze_report)
    write_json(compare_dir / "frozen_inputs.json", freeze_report)

    # E1: fixed evaluation-only BM25, using the already fixed Phase 9 tokenizer/config.
    bm25 = EvaluationBM25(frozen["corpus"], corpus_sha256=frozen["hashes"]["evaluation_corpus_v2"],
                          git_commit=git_commit, created_at=frozen_time)
    bm25_config = {
        "index_id": "E1_grounded_bm25_v1", "index_type": "evaluation_only_in_memory_bm25",
        "corpus_sha256": frozen["hashes"]["evaluation_corpus_v2"],
        "retrieval_chunk_count": len(frozen["corpus"]), "document_count": frozen["corpus_profile"]["document_count"],
        "page_count": frozen["corpus_profile"]["page_count"], "tokenizer": TOKENIZER,
        "bm25_configuration": dict(BM25_CONFIG), "created_at": frozen_time, "git_commit": git_commit,
        "persistent_storage": False, "production_retriever_imported": False,
        "eligibility_filter": {"retrieval_role": "retrieval", "canonical_chunk": True,
                                "canonical_document": True, "noncanonical_duplicates_excluded": True,
                                "context_only_excluded": True, "benchmark_eligibility_filter": False},
    }
    bm25_index_directory = root / "data/evaluation/indexes/E1_grounded_bm25_v1"
    write_json(bm25_index_directory / "index_manifest.json", bm25_config)
    write_json(e1_dir / "index_manifest.json", bm25_config)
    e1 = run_retriever(
        experiment_id="E1_grounded_bm25_v1", retriever=bm25, questions=frozen["questions"], corpus=frozen["corpus"],
        corpus_sha256=frozen["hashes"]["evaluation_corpus_v2"], question_sha256=frozen["hashes"]["grounded_questions_v1"],
        evidence_pool_sha256=frozen["hashes"]["evidence_pool_v1"], evidence_resolution_sha256=frozen["evidence_resolution_sha256"],
        git_commit=git_commit, timestamp=frozen_time, output_directory=e1_dir, retriever_config=bm25_config)
    e1_determinism = _determinism_check(bm25, frozen["questions"])
    write_json(e1_dir / "determinism_validation.json", e1_determinism)
    if e1_determinism["status"] != "passed":
        raise RuntimeError("E1 BM25 ranking determinism check failed")
    e1_recompute = validate_metric_recompute(e1_dir, frozen["questions"], frozen["corpus"])
    if e1_recompute["status"] != "passed":
        raise RuntimeError("E1 metric recomputation validation failed")

    # E2 preflight: a runtime failure blocks Dense; it never substitutes another model.
    runtime = OllamaEmbeddingRuntime()
    try:
        runtime_metadata = runtime.preflight()
    except Exception as exc:
        blocked = dense_preflight_failure(e2_dir, timestamp=frozen_time, frozen=frozen, git_commit=git_commit, error=str(exc))
        after = protected_file_snapshot(root)
        compatibility = verify_protected_snapshot(protected_before, after)
        write_json(compare_dir / "production_compatibility.json", compatibility)
        return {"status": "e2_blocked_runtime", "E1": e1["manifest"], "E2": blocked,
                "compatibility": compatibility, "error": str(exc)}

    # E2: rebuild every vector from the frozen corpus and BGE-M3 runtime.
    try:
        dense, dense_index_manifest = build_dense_index(root, frozen, runtime, runtime_metadata, git_commit, frozen_time)
    except Exception as exc:
        blocked = dense_preflight_failure(e2_dir, timestamp=frozen_time, frozen=frozen, git_commit=git_commit,
                                          error=f"Dense index construction failed: {exc}")
        after = protected_file_snapshot(root)
        compatibility = verify_protected_snapshot(protected_before, after)
        write_json(compare_dir / "production_compatibility.json", compatibility)
        return {"status": "e2_blocked_runtime", "E1": e1["manifest"], "E2": blocked,
                "compatibility": compatibility, "error": str(exc)}
    dense_config = {**dense_index_manifest, "retriever_type": "dense", "model": runtime_metadata}
    write_json(e2_dir / "index_manifest.json", dense_index_manifest)
    e2 = run_retriever(
        experiment_id="E2_grounded_dense_v1", retriever=dense, questions=frozen["questions"], corpus=frozen["corpus"],
        corpus_sha256=frozen["hashes"]["evaluation_corpus_v2"], question_sha256=frozen["hashes"]["grounded_questions_v1"],
        evidence_pool_sha256=frozen["hashes"]["evidence_pool_v1"], evidence_resolution_sha256=frozen["evidence_resolution_sha256"],
        git_commit=git_commit, timestamp=frozen_time, output_directory=e2_dir, retriever_config=dense_config)
    e2_determinism = _determinism_check(dense, frozen["questions"])
    write_json(e2_dir / "determinism_validation.json", e2_determinism)
    if e2_determinism["status"] != "passed":
        raise RuntimeError("E2 Dense ranking determinism check failed over the frozen embedding index")
    e2_recompute = validate_metric_recompute(e2_dir, frozen["questions"], frozen["corpus"])
    if e2_recompute["status"] != "passed":
        raise RuntimeError("E2 metric recomputation validation failed")

    fairness = fairness_validation(e1, e2, frozen)
    write_json(compare_dir / "fairness_validation.json", fairness)
    paired_hits, paired_rows, paired_rank_rows = paired_comparison(e1, e2)
    bootstrap = bootstrap_comparison(e1["rows"], e2["rows"])
    leakage = leakage_audit(frozen["questions"], {str(row["chunk_id"]): row for row in frozen["corpus"]})
    leakage_rows = leakage.pop("rows")
    error_report = error_comparison(e1["errors"], e2["errors"], paired_rows)
    write_json(compare_dir / "comparison.json", {
        "experiment_id": "E1_vs_E2_grounded_v1", "benchmark_type": "AI-generated corpus-grounded Silver; not human Gold",
        "question_count": len(frozen["questions"]), "corpus_profile": frozen["corpus_profile"],
        "frozen_input_sha256": frozen["hashes"], "required_evidence_resolution_sha256": frozen["evidence_resolution_sha256"],
        "E1_overall": _summarize_rows(e1["rows"]), "E2_overall": _summarize_rows(e2["rows"]),
        "E2_minus_E1": _comparison_metrics(e1["rows"], e2["rows"]),
        "paired_required_evidence_hits": paired_hits, "fairness_validation": fairness,
        "query_style_counts": dict(Counter(str(row.get("query_style")) for row in frozen["questions"])),
        "overlap_bucket_counts": dict(Counter(lexical_overlap_bucket(float(q.get("lexical_overlap") or 0.0))
                                               for q in frozen["questions"])),
        "species_note": "虱目魚 has zero benchmark questions; no 虱目魚 score is calculated.",
        "small_slice_notes": {"multi_document": 1, "calculation": 3, "interpretation": "descriptive only"},
        "human_gold_accuracy_claim": False,
    })
    write_json(compare_dir / "paired_hits.json", paired_hits)
    write_jsonl(compare_dir / "paired_hits.jsonl", paired_rows)
    write_jsonl(compare_dir / "paired_rank_analysis.jsonl", paired_rank_rows)
    write_json(compare_dir / "paired_rank_analysis.json", {
        "question_count": len(paired_rank_rows),
        "rank_difference_sentinel": None,
        "rank_difference_note": "Ranks outside Top 10 are null in Top-10 paired differences; full rank is retained separately when resolved.",
        "mean_delta_dense_minus_bm25": paired_hits["rank_difference_top10"]["mean_dense_minus_bm25"],
        "median_delta_dense_minus_bm25": paired_hits["rank_difference_top10"]["median_dense_minus_bm25"],
        "hit_partition": {k: paired_hits[f"hit@{k}"] for k in (1, 5, 10)},
    })
    write_json(compare_dir / "bootstrap_ci.json", bootstrap)
    write_json(compare_dir / "leakage_audit.json", leakage)
    write_jsonl(compare_dir / "leakage_audit_rows.jsonl", leakage_rows)
    write_json(compare_dir / "error_analysis.json", error_report)
    write_jsonl(compare_dir / "errors.jsonl", error_report["automatic_error_rows"])
    write_json(compare_dir / "input_freeze_validation.json", {
        "current_hashes_equal_frozen_start": {
            name: sha256_file(path) == frozen["hashes"][name] for name, path in frozen["paths"].items()},
        "phase11_manifest_version": frozen["phase11_manifest"].get("dataset_version"),
        "all_hashes_match_phase11_and_start": all(sha256_file(path) == frozen["hashes"][name] for name, path in frozen["paths"].items()),
    })
    style_expected = {"direct": 58, "paraphrase": 55, "contextual": 56}
    style_actual = dict(Counter(str(row.get("query_style")) for row in frozen["questions"]))
    write_json(compare_dir / "query_style_validation.json", {"expected": style_expected, "actual": style_actual,
                                                               "status": "passed" if style_actual == style_expected else "review"})
    if style_actual != style_expected:
        raise RuntimeError(f"Unexpected query-style distribution: {style_actual}")
    summary = _summary_markdown(frozen=frozen, e1=e1, e2=e2, paired_hits=paired_hits,
                                bootstrap=bootstrap, fairness=fairness, runtime_metadata=runtime_metadata, leakage=leakage)
    (compare_dir / "comparison_summary.md").write_text(summary, encoding="utf-8", newline="\n")

    # Protect the frozen data and production store; the evaluation indexes/reports are new paths.
    after = protected_file_snapshot(root)
    compatibility = verify_protected_snapshot(protected_before, after)
    write_json(compare_dir / "production_compatibility.json", compatibility)
    if compatibility["status"] != "passed":
        raise RuntimeError(f"Protected production/previous-phase files changed: {compatibility['changed_files']}")
    return {
        "status": "completed", "freeze": freeze_report, "corpus_profile": frozen["corpus_profile"],
        "E1": {"manifest": e1["manifest"], "overall": _summarize_rows(e1["rows"]), "errors": e1["errors"],
               "determinism": e1_determinism, "metric_recompute": e1_recompute},
        "E2": {"manifest": e2["manifest"], "index_manifest": dense_index_manifest,
               "overall": _summarize_rows(e2["rows"]), "errors": e2["errors"],
               "determinism": e2_determinism, "metric_recompute": e2_recompute},
        "paired_hits": paired_hits, "bootstrap": bootstrap, "fairness": fairness,
        "leakage": leakage, "errors": error_report, "compatibility": compatibility,
        "report_directory": str(compare_dir),
    }
