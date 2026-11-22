"""Run E1 BM25 against an AI-generated Silver dataset without touching production RAG."""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .corpus import read_jsonl, write_json
from .retrieval.metrics import ndcg_at, precision_at, recall_at, reciprocal_rank
from .retrieval.models import GoldEvidence, ResolvedGold, RetrievalResult, RankedHit
from .retrievers.bm25 import EvaluationBM25
from .silver import ROOT, MAPPING_STATUSES, coverage_report, sha256_file, validate_silver_question

EXPERIMENT_ID = "E1_bm25_silver_v1"
TOP_K = (1, 3, 5, 10)
PRIMARY_MAPPING = {"exact", "high_confidence"}


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")


def _silver_evidence(question: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> ResolvedGold:
    evidence = []
    for item in question.get("mapped_chunks") or []:
        chunk_id = str(item.get("chunk_id") or "")
        row = corpus_by_id.get(chunk_id)
        if row is None:
            raise ValueError(f"{question.get('question_id')}: auto-mapped chunk not found: {chunk_id}")
        if row.get("retrieval_role") != "retrieval":
            raise ValueError(f"{question.get('question_id')}: mapped chunk is not retrieval role: {chunk_id}")
        if row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
            raise ValueError(f"{question.get('question_id')}: mapped chunk is non-canonical duplicate: {chunk_id}")
        page = row.get("page_start")
        if page is None:
            raise ValueError(f"{question.get('question_id')}: mapped chunk lacks page: {chunk_id}")
        evidence.append(GoldEvidence(chunk_id, str(row.get("document_id") or ""), int(page), "silver_auto_mapped", int(row.get("page_end") or page)))
    return ResolvedGold(str(question.get("question_id")), required=tuple(evidence), metadata={
        "category": question.get("category"), "species": question.get("species_candidate"),
        "difficulty": question.get("difficulty_candidate"),
    })


def _metrics(result: RetrievalResult, evidence: ResolvedGold) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for level in ("chunk", "page", "document"):
        values: dict[str, float] = {}
        for k in TOP_K:
            values[f"recall@{k}"] = recall_at(result, evidence, k, level)
            values[f"precision@{k}"] = precision_at(result, evidence, k, level)
            values[f"ndcg@{k}"] = ndcg_at(result, evidence, k, level)
        values["mrr"] = reciprocal_rank(result, evidence, level)
        output[level] = values
    return output


def _fact_coverage(question: dict[str, Any], hits: list[RankedHit]) -> dict[str, Any]:
    top_ids = {hit.chunk_id for hit in hits[:10]}
    fact_rows = question.get("fact_mapping") or []
    mapped_facts = [row for row in fact_rows if row.get("mapped_chunk_ids")]
    covered = [row for row in mapped_facts if top_ids.intersection(str(value) for value in row.get("mapped_chunk_ids") or [])]
    return {
        "expected_fact_count": len(fact_rows),
        "mapped_expected_fact_count": len(mapped_facts),
        "retrieved_expected_fact_count": len(covered),
        "expected_fact_coverage": len(covered) / len(mapped_facts) if mapped_facts else None,
        "all_mapped_expected_facts_retrieved": bool(mapped_facts) and len(mapped_facts) == len(covered),
    }


def _multi_document(question: dict[str, Any], hits: list[RankedHit]) -> dict[str, Any]:
    expected = set(str(value) for value in question.get("mapped_documents") or [])
    retrieved = {hit.document_id for hit in hits[:10]}
    intersection = expected & retrieved
    return {
        "expected_document_count": len(expected),
        "retrieved_expected_document_count": len(intersection),
        "all_expected_documents_retrieved": bool(expected) and expected.issubset(retrieved),
        "multi_document": len(expected) > 1,
        "multi_document_partial": len(expected) > 1 and bool(intersection) and not expected.issubset(retrieved),
    }


def _trace_rows(question: dict[str, Any], hits: list[RankedHit], evidence: ResolvedGold) -> list[dict[str, Any]]:
    expected_chunks = {item.chunk_id for item in (*evidence.required, *evidence.acceptable)}
    expected_documents = {item.document_id for item in (*evidence.required, *evidence.acceptable)}
    expected_pages = {
        (item.document_id, page)
        for item in (*evidence.required, *evidence.acceptable)
        if item.page is not None
        for page in range(item.page, (item.page_end or item.page) + 1)
    }
    trace = []
    for hit in hits[:10]:
        hit_pages = set(range(hit.page, (hit.page_end or hit.page) + 1)) if hit.page is not None else set()
        trace.append({
            "question_id": question["question_id"], "question": question.get("question"),
            "benchmark_type": "silver", "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
            "species": question.get("species_candidate"), "rank": hit.rank,
            "chunk_id": hit.chunk_id, "document_id": hit.document_id, "page": hit.page,
            "page_end": hit.page_end,
            "score": hit.raw_score, "expected_chunk_match": hit.chunk_id in expected_chunks,
            "expected_page_match": any((hit.document_id, page) in expected_pages for page in hit_pages),
            "expected_document_match": hit.document_id in expected_documents,
            "mapping_status": question.get("evidence_mapping_status"),
        })
    return trace


def _error_candidate(question: dict[str, Any], hits: list[RankedHit], all_hits: list[RankedHit], evidence: ResolvedGold) -> dict[str, Any] | None:
    if question.get("evidence_mapping_status") not in PRIMARY_MAPPING:
        return None
    expected_chunks = {item.chunk_id for item in evidence.required}
    expected_docs = {item.document_id for item in evidence.required}
    expected_pages = {(item.document_id, item.page) for item in evidence.required if item.page is not None}
    top10 = hits[:10]
    top_ids = {hit.chunk_id for hit in top10}
    if expected_chunks & top_ids:
        return None
    all_ids = {hit.chunk_id for hit in all_hits}
    top_docs = {hit.document_id for hit in top10}
    top_pages = {(hit.document_id, hit.page) for hit in top10 if hit.page is not None}
    if len(expected_docs) > 1 and expected_docs & top_docs and not expected_docs.issubset(top_docs):
        category = "multi_document_partial"
    elif expected_chunks & all_ids:
        category = "relevant_below_k"
    elif expected_docs & top_docs and expected_pages & top_pages:
        category = "correct_page_wrong_chunk"
    elif expected_docs & top_docs:
        category = "correct_document_wrong_page"
    elif expected_docs:
        category = "wrong_document"
    elif not any(hit.raw_score for hit in top10):
        category = "query_term_mismatch"
    else:
        category = "no_relevant_retrieved"
    return {
        "benchmark_type": "silver", "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
        "question_id": question["question_id"], "mapping_status": question.get("evidence_mapping_status"),
        "risk_level": question.get("risk_level"), "category": category,
        "classification": "automatic_candidate", "confidence": "low", "human_review_required": True,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("metrics") is not None]
    metric_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in eligible:
        for granularity, scores in row["metrics"].items():
            for metric, value in scores.items():
                metric_values[granularity][metric].append(float(value))
    means = {
        granularity: {metric: sum(values) / len(values) for metric, values in sorted(metrics.items()) if values}
        for granularity, metrics in sorted(metric_values.items())
    }
    return {
        "benchmark_type": "silver", "generation_source": "ai_question_bank",
        "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
        "scored_question_count": len(eligible), "retrieved_question_count": len(rows),
        "mean_metrics": means,
        "expected_fact_recall_at_10": _mean([row["expected_fact_coverage"]["expected_fact_coverage"] for row in eligible if row.get("expected_fact_coverage", {}).get("expected_fact_coverage") is not None]),
        "all_mapped_expected_facts_retrieved_rate": _mean([float(row["expected_fact_coverage"]["all_mapped_expected_facts_retrieved"]) for row in eligible]),
        "all_expected_documents_retrieved_rate": _mean([float(row["multi_document_coverage"]["all_expected_documents_retrieved"]) for row in eligible if row.get("multi_document_coverage", {}).get("expected_document_count", 0) > 0]),
        "multi_document_question_count": sum(row.get("multi_document_coverage", {}).get("multi_document") is True for row in eligible),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _groups(
    rows: list[dict[str, Any]], field: str, *, all_questions: list[dict[str, Any]] | None = None,
    include_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["question"].get(field) or "unknown")].append(row)
    total_groups: dict[str, int] = Counter()
    question_field = {"species": "species_candidate", "category": "category", "question_type": "question_type", "risk_level": "risk_level", "mapping_confidence": "evidence_mapping_status"}.get(field, field)
    for question in all_questions or []:
        total_groups[str(question.get(question_field) or "unknown")] += 1
    keys = set(groups) | set(total_groups) | set(include_values)
    report = {}
    for key in sorted(keys):
        item = _aggregate(groups.get(key, []))
        item["silver_question_count"] = total_groups.get(key, 0)
        item["primary_evaluable_count"] = item["scored_question_count"]
        report[key] = item
    return report


def run_e1_bm25_silver(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    questions_path = root / "data" / "evaluation" / "silver" / "questions_v1.jsonl"
    corpus_manifest_path = root / "data" / "evaluation" / "corpus_manifest.json"
    questions = read_jsonl(questions_path)
    schema_errors = [(row.get("question_id"), validate_silver_question(row)) for row in questions]
    schema_errors = [(question_id, errors) for question_id, errors in schema_errors if errors]
    if not questions:
        raise ValueError("Silver question dataset is empty")
    if schema_errors:
        raise ValueError(f"Silver schema validation failed: {schema_errors[:5]}")
    start_corpus_sha, start_silver_sha = sha256_file(corpus_path), sha256_file(questions_path)
    corpus_manifest = _read_json(corpus_manifest_path)
    manifest_sha = corpus_manifest.get("corpus_sha256") or corpus_manifest.get("evaluation_corpus_sha256")
    if manifest_sha not in (None, start_corpus_sha):
        raise ValueError("Evaluation Corpus v1 checksum does not match its manifest")
    corpus_rows = read_jsonl(corpus_path)
    retriever = EvaluationBM25(corpus_rows, corpus_sha256=start_corpus_sha, git_commit=_git_commit(root))
    corpus_by_id = {str(row.get("chunk_id")): row for row in corpus_rows if row.get("chunk_id")}
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for question in questions:
        evidence = _silver_evidence(question, corpus_by_id)
        all_hits = retriever.rank_all(str(question.get("question") or ""))
        top_hits = all_hits[:10]
        result = RetrievalResult(str(question["question_id"]), tuple(top_hits))
        status = str(question.get("evidence_mapping_status"))
        metric_data = _metrics(result, evidence) if status in PRIMARY_MAPPING or status == "medium_confidence" else None
        fact_coverage = _fact_coverage(question, top_hits)
        multi_coverage = _multi_document(question, top_hits)
        row = {
            "benchmark_type": "silver", "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
            "question": {
                "benchmark_type": "silver", "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
                "question_id": question["question_id"], "question": question.get("question"),
                "species": question.get("species_candidate"), "category": question.get("category"),
                "question_type": question.get("question_type"), "risk_level": question.get("risk_level"),
                "mapping_confidence": status,
            },
            "metrics": metric_data,
            "expected_fact_coverage": fact_coverage,
            "multi_document_coverage": multi_coverage,
            "retrieval_top_k": 10,
            "scored_as_primary": status in PRIMARY_MAPPING,
            "scored_as_secondary": status == "medium_confidence",
        }
        rows.append(row)
        traces.extend(_trace_rows(question, top_hits, evidence))
        candidate = _error_candidate(question, top_hits, all_hits, evidence)
        if candidate:
            errors.append(candidate)

    traces_by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        traces_by_question[str(trace["question_id"])].append(trace)
    recompute_passed = True
    for question, row in zip(questions, rows):
        if row.get("metrics") is None:
            continue
        question_id = str(question["question_id"])
        trace_hits = [RankedHit(
            rank=int(trace["rank"]), chunk_id=str(trace["chunk_id"]), document_id=str(trace["document_id"]),
            page=int(trace["page"]) if trace.get("page") is not None else None,
            raw_score=float(trace["score"]) if trace.get("score") is not None else None,
            page_end=int(trace["page_end"]) if trace.get("page_end") is not None else None,
        ) for trace in traces_by_question.get(question_id, [])]
        rebuilt = _metrics(RetrievalResult(question_id, tuple(trace_hits)), _silver_evidence(question, corpus_by_id))
        if rebuilt != row["metrics"]:
            recompute_passed = False
            break

    end_corpus_sha, end_silver_sha = sha256_file(corpus_path), sha256_file(questions_path)
    if start_corpus_sha != end_corpus_sha or start_silver_sha != end_silver_sha:
        raise RuntimeError("Frozen corpus or Silver dataset changed during the experiment")

    output = root / "reports" / "evaluation" / "experiments" / EXPERIMENT_ID
    output.mkdir(parents=True, exist_ok=True)
    coverage = coverage_report(questions)
    readiness_path = root / "reports" / "evaluation" / "silver_benchmark_readiness.json"
    readiness = _read_json(readiness_path) if readiness_path.exists() else {}
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "benchmark_type": "silver",
        "generation_source": "ai_question_bank",
        "question_origin": "ai_generated",
        "evidence_mapping_type": "auto_mapped",
        "silver_dataset_version": "silver_questions_v1",
        "silver_dataset_sha256": start_silver_sha,
        "evaluation_corpus_version": "evaluation-corpus-v1",
        "evaluation_corpus_sha256": start_corpus_sha,
        "retriever_type": "bm25",
        "retriever_config": {"tokenizer": retriever.index_manifest["tokenizer"], **retriever.index_manifest["bm25_configuration"]},
        "index_manifest": retriever.index_manifest,
        "top_k": list(TOP_K),
        "retrieval_trace_top_k": 10,
        "embedding_model": None,
        "embedding_dimension": None,
        "chunking_version": "chunking-v2-shadow-evaluation-corpus-v1",
        "git_commit": _git_commit(root),
        "question_count": len(questions),
        "primary_mapping_statuses": sorted(PRIMARY_MAPPING),
        "evidence_mapping_backend": "lexical_only; embedding runtime unavailable during Silver mapping",
        "primary_evaluable_questions": coverage["primary_evaluable_questions"],
        "medium_confidence_secondary_questions": coverage["medium_confidence"],
        "low_confidence_and_unmapped_scored": False,
        "ranking_uses_expected_evidence": False,
        "production_retrieval_used": False,
        "quality_claim": "Retrieval metrics over AI-generated Silver references and automatically mapped evidence; not human Gold accuracy and not a claim that reference answers are authoritative or absolutely correct.",
        "notes": "E1 BM25 only. Dense, RRF, reranker, answer generation, and answer evaluation were not run.",
        "human_gold_readiness": readiness.get("smoke_test_ready", False),
    }
    aggregate_rows = [row for row in rows if row.get("scored_as_primary")]
    write_json(output / "experiment_manifest.json", manifest)
    write_json(output / "index_manifest.json", retriever.index_manifest)
    write_json(output / "overall.json", _aggregate(aggregate_rows))
    species_values = tuple(sorted({str(question.get("species_candidate") or "unknown") for question in questions}))
    category_values = tuple(sorted({str(question.get("category") or "unknown") for question in questions}))
    question_type_values = tuple(sorted({str(question.get("question_type") or "unknown") for question in questions}))
    write_json(output / "by_species.json", _groups(aggregate_rows, "species", all_questions=questions, include_values=species_values))
    write_json(output / "by_category.json", _groups(aggregate_rows, "category", all_questions=questions, include_values=category_values))
    write_json(output / "by_question_type.json", _groups(aggregate_rows, "question_type", all_questions=questions, include_values=question_type_values))
    write_json(output / "by_risk.json", _groups(aggregate_rows, "risk_level", all_questions=questions, include_values=("normal", "high")))
    write_json(output / "by_mapping_confidence.json", _groups(aggregate_rows, "mapping_confidence", all_questions=questions, include_values=("exact", "high_confidence", "medium_confidence")))
    write_json(output / "medium_confidence_secondary.json", _aggregate([row for row in rows if row.get("scored_as_secondary")]))
    _write_jsonl(output / "per_question.jsonl", rows)
    _write_jsonl(output / "ranking_traces.jsonl", traces)
    write_json(output / "coverage.json", coverage)
    _write_jsonl(output / "errors.jsonl", errors)
    validation = {
        "benchmark_type": "silver", "generation_source": "ai_question_bank",
        "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
        "all_questions_have_traces": all(any(trace["question_id"] == row["question"]["question_id"] for trace in traces) for row in rows),
        "questions_with_trace_count": len({trace["question_id"] for trace in traces}),
        "expected_chunk_references_resolve": True,
        "trace_rows": len(traces),
        "max_trace_rank": max((trace["rank"] for trace in traces), default=0),
        "corpus_sha256_unchanged": start_corpus_sha == end_corpus_sha,
        "silver_sha256_unchanged": start_silver_sha == end_silver_sha,
        "metric_recompute_from_ranking_traces": recompute_passed,
        "deterministic_tie_break": "score_desc_then_chunk_id_asc",
        "manifest_valid": all(manifest.get(field) is not None for field in ("experiment_id", "evaluation_corpus_sha256", "silver_dataset_sha256", "retriever_type", "top_k", "git_commit")),
    }
    write_json(output / "validation.json", validation)
    taxonomy = (
        "no_relevant_retrieved", "relevant_below_k", "wrong_document",
        "correct_document_wrong_page", "correct_page_wrong_chunk", "duplicate_competition",
        "metadata_filter_error", "query_term_mismatch", "multi_document_partial", "unknown",
    )
    write_json(output / "error_summary.json", {
        "benchmark_type": "silver", "generation_source": "ai_question_bank",
        "question_origin": "ai_generated", "evidence_mapping_type": "auto_mapped",
        "automatic_error_candidates": len(errors),
        "by_category": {category: sum(row.get("category") == category for row in errors) for category in taxonomy},
        "note": "Automatic low-confidence candidates for review; low-confidence and unmapped Silver questions are excluded from retrieval failure counts.",
    })
    return {"manifest": manifest, "overall": _aggregate(aggregate_rows), "coverage": coverage, "validation": validation, "errors": errors, "output_directory": str(output)}
