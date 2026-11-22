"""Load and validate immutable inputs for Phase 15 generation experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CORPUS_PATH = Path("data/evaluation/corpus_v2.jsonl")
QUESTIONS_PATH = Path("data/evaluation/grounded/questions_v1.jsonl")
E4_DIR = Path("reports/evaluation/experiments/E4_grounded_rrf_reranker_v1")
EXPECTED_CORPUS_SHA256 = "540a7dfa641fdbf9c2246feea75a226ade41a8e85d5c995fa5b3c8514aa03162"
EXPECTED_QUESTIONS_SHA256 = "7f221e36328763c0f71d0bb8fb3b762ef15faad05f6de5080301e7ad8b4991d5"
EXPECTED_E4_TRACE_SHA256 = "9f5285ab64552f98b3b90acdba9ff19cc01c9e1bccb9eb935f145790c265ec9d"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def canonical_top5_sha256(questions: list[dict[str, Any]], per_question_rows: list[dict[str, Any]]) -> str:
    rows_by_id = {str(row["question_id"]): row for row in per_question_rows}
    ordered = []
    for question in questions:
        qid = str(question["question_id"])
        row = rows_by_id.get(qid)
        if row is None:
            raise ValueError(f"E4 per-question output missing question: {qid}")
        top10 = row.get("retrieval_top10_chunk_ids") or []
        if len(top10) < 5:
            raise ValueError(f"E4 output has fewer than five chunks: {qid}")
        ordered.append({"question_id": qid, "top5_chunk_ids": top10[:5]})
    payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_frozen_inputs(root: Path) -> dict[str, Any]:
    corpus_path = root / CORPUS_PATH
    questions_path = root / QUESTIONS_PATH
    e4_dir = root / E4_DIR
    manifest_path = e4_dir / "experiment_manifest.json"
    trace_path = e4_dir / "ranking_traces.jsonl"
    per_question_path = e4_dir / "per_question.jsonl"
    for path in (corpus_path, questions_path, manifest_path, trace_path, per_question_path):
        if not path.is_file():
            raise ValueError(f"Required frozen input is missing: {path.relative_to(root)}")

    corpus_sha = sha256_file(corpus_path)
    questions_sha = sha256_file(questions_path)
    trace_sha = sha256_file(trace_path)
    manifest_sha = sha256_file(manifest_path)
    if corpus_sha != EXPECTED_CORPUS_SHA256:
        raise ValueError("Evaluation Corpus v2 checksum differs from the frozen Phase 12 input")
    if questions_sha != EXPECTED_QUESTIONS_SHA256:
        raise ValueError("Grounded Silver v1 checksum differs from the frozen Phase 12 input")
    if trace_sha != EXPECTED_E4_TRACE_SHA256:
        raise ValueError("E4 ranking trace checksum differs from the frozen Phase 14 output")

    corpus = read_jsonl(corpus_path)
    questions = read_jsonl(questions_path)
    e4_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    per_question = read_jsonl(per_question_path)
    trace = read_jsonl(trace_path)
    if len(questions) != 169:
        raise ValueError(f"Expected 169 Grounded Silver questions, found {len(questions)}")
    if e4_manifest.get("evaluation_corpus_v2_sha256") != corpus_sha:
        raise ValueError("E4 manifest corpus checksum does not match current corpus")
    if e4_manifest.get("grounded_questions_v1_sha256") != questions_sha:
        raise ValueError("E4 manifest question checksum does not match current questions")
    if e4_manifest.get("reranker", {}).get("model_id") != "BAAI/bge-reranker-v2-m3":
        raise ValueError("E4 manifest does not identify the expected reranker")
    if e4_manifest.get("reranker", {}).get("revision") != "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e":
        raise ValueError("E4 reranker revision differs from the frozen Phase 14 model")

    top5_sha = canonical_top5_sha256(questions, per_question)
    question_ids = [str(row["question_id"]) for row in questions]
    if len(set(question_ids)) != 169:
        raise ValueError("Grounded Silver question IDs are not unique")
    trace_top10: dict[str, list[str]] = {}
    for qid in question_ids:
        rows = sorted((row for row in trace if str(row.get("question_id")) == qid), key=lambda row: int(row["rank"]))
        if len(rows) < 10 or [int(row["rank"]) for row in rows[:10]] != list(range(1, 11)):
            raise ValueError(f"E4 trace does not contain a contiguous Top-10 for {qid}")
        trace_top10[qid] = [str(row["chunk_id"]) for row in rows[:10]]
        expected = next(row for row in per_question if str(row["question_id"]) == qid)["retrieval_top10_chunk_ids"]
        if trace_top10[qid] != expected:
            raise ValueError(f"E4 ranking trace and per-question Top-10 mismatch for {qid}")

    corpus_by_id: dict[str, dict[str, Any]] = {}
    for row in corpus:
        chunk_id = str(row.get("chunk_id") or "")
        if not chunk_id or chunk_id in corpus_by_id:
            raise ValueError(f"Corpus chunk IDs are missing or duplicated: {chunk_id!r}")
        corpus_by_id[chunk_id] = row
    return {
        "corpus": corpus,
        "corpus_by_id": corpus_by_id,
        "questions": questions,
        "e4_manifest": e4_manifest,
        "e4_trace": trace,
        "e4_trace_by_question": {
            qid: sorted((row for row in trace if str(row.get("question_id")) == qid), key=lambda row: int(row["rank"]))
            for qid in question_ids
        },
        "per_question": per_question,
        "hashes": {
            "evaluation_corpus_v2_sha256": corpus_sha,
            "grounded_silver_v1_sha256": questions_sha,
            "e4_manifest_sha256": manifest_sha,
            "e4_ranking_trace_sha256": trace_sha,
            "e4_top5_sha256": top5_sha,
        },
        "question_count": len(questions),
    }
