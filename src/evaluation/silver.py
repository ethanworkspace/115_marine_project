"""Build an AI-generated Silver retrieval benchmark with explicit auto-mapping confidence.

Silver references are workbook candidates, not human Gold annotations and not
authoritative answer labels. Mapping code only proposes corpus evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .corpus import read_jsonl, write_json
from .question_bank_import import read_xlsx_sheets

ROOT = Path(__file__).resolve().parents[2]
MAPPING_STATUSES = ("exact", "high_confidence", "medium_confidence", "low_confidence", "unmapped")
SILVER_REQUIRED = (
    "question_id", "species_candidate", "question", "reference_answer", "category",
    "question_type", "risk_level", "source_workbook", "source_sheet", "source_row",
    "expected_sources", "expected_facts", "benchmark_type", "generation_source", "question_origin",
    "evidence_mapping_type", "mapping_backend",
    "evidence_mapping_status", "mapped_chunks", "mapped_pages", "mapped_documents",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    return list(dict.fromkeys(part.strip() for part in re.split(r"[;,，；、\s]+", str(value)) if part.strip()))


def _normalized_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, ""))


def _norm_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _terms(value: Any) -> set[str]:
    terms: set[str] = set()
    for match in re.finditer(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+", str(value or "").casefold()):
        token = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) == 1:
                terms.add(token)
            else:
                terms.update(token[index:index + 2] for index in range(len(token) - 1))
        else:
            terms.add(token)
    return terms


def _sheet_records(rows: list[tuple[int, list[Any]]], header_marker: str) -> list[dict[str, Any]]:
    header_at = next((index for index, (_, values) in enumerate(rows[:16]) if header_marker in values), None)
    if header_at is None:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[header_at][1]]
    output = []
    for row_number, values in rows[header_at + 1:]:
        row = {header: values[index] if index < len(values) else None for index, header in enumerate(headers) if header}
        if any(value not in (None, "") for value in row.values()):
            row["_row_number"] = row_number
            output.append(row)
    return output


def _workbook_reference(candidate: dict[str, Any], root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    relative = str(candidate.get("source_workbook") or "")
    path = root / Path(relative.replace("/", "/"))
    if not path.is_file():
        return {}, {}
    try:
        sheets = read_xlsx_sheets(path)
    except (OSError, ValueError, KeyError):
        return {}, {}
    sources = _sheet_records(sheets.get("資料來源", []), "來源ID")
    facts = _sheet_records(sheets.get("事實資料庫", []), "事實ID")
    source_by_id = {str(row.get("來源ID")): row for row in sources if row.get("來源ID")}
    fact_by_id = {str(row.get("事實ID")): row for row in facts if row.get("事實ID")}
    return source_by_id, fact_by_id


def _eligible_corpus(corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select first-stage retrieval rows, independent of human-Gold eligibility."""
    rows = []
    for row in corpus:
        if row.get("retrieval_role") != "retrieval":
            continue
        if row.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
            continue
        if row.get("canonical_chunk_id") != row.get("chunk_id"):
            continue
        if row.get("canonical_document_id") != row.get("document_id"):
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("chunk_id") or ""))
    return rows


def _all_identifiers(row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("source_id", "fact_id", "fact_ids", "source_ids", "expected_fact_ids"):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            values.update(str(item) for item in value if item is not None)
        elif value is not None:
            values.update(_split_ids(value))
    return values


def _text_similarity(
    query: str, row: dict[str, Any], corpus_df: dict[str, int], corpus_size: int,
    body_terms: set[str] | None = None,
) -> float:
    query_terms = _terms(query)
    if len(query_terms) < 2:
        return 0.0
    body = str(row.get("text") or "")
    body_terms = body_terms if body_terms is not None else _terms(body)
    if not body_terms:
        return 0.0
    ordered_terms = sorted(query_terms)
    denominator = sum(math.log((corpus_size + 1) / (corpus_df.get(term, 0) + 1)) + 1.0 for term in ordered_terms)
    if denominator <= 0:
        return 0.0
    numerator = sum(
        math.log((corpus_size + 1) / (corpus_df.get(term, 0) + 1)) + 1.0
        for term in ordered_terms if term in body_terms
    )
    return numerator / denominator


def _build_df(corpus: list[dict[str, Any]]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for row in corpus:
        df.update(_terms(row.get("text") or ""))
    return dict(df)


def _resolve_fact(
    fact: dict[str, Any], sources: list[dict[str, Any]], corpus: list[dict[str, Any]], df: dict[str, int],
    fallback_query: str = "", terms_index: dict[str, set[str]] | None = None,
    normalized_text_index: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, float | None, str]:
    fact_id = str(fact.get("fact_id") or "")
    source_ids = {str(value) for value in fact.get("source_ids", [])}
    source_urls = {_normalized_url(source.get("source_url")) for source in sources if _normalized_url(source.get("source_url"))}
    fact_statement = str(fact.get("statement") or "")

    # Identifiers and source URL/title matches are used only when those identifiers
    # really occur in corpus metadata; workbook-only IDs are not inferred.
    id_matches = [row for row in corpus if fact_id and fact_id in _all_identifiers(row)]
    id_matches += [row for row in corpus if source_ids & _all_identifiers(row)]
    if id_matches:
        unique = {str(row.get("chunk_id")): row for row in id_matches if row.get("chunk_id")}
        return list(unique.values()), "exact", 1.0, "exact_source_or_fact_identifier"
    title_norms = {_norm_text(source.get("document_title")) for source in sources if source.get("document_title")}
    title_matches = [row for row in corpus if _norm_text(row.get("source_title")) in title_norms and _norm_text(row.get("source_title"))]
    if title_matches:
        unique = {str(row.get("chunk_id")): row for row in title_matches if row.get("chunk_id")}
        return list(unique.values()), "exact", 1.0, "exact_document_title"
    url_matches = [row for row in corpus if _normalized_url(row.get("source_url")) in source_urls]
    if url_matches:
        source_pages = {int(source.get("page") or source.get("page_number")) for source in sources if source.get("page") or source.get("page_number")}
        if source_pages:
            page_matches = [row for row in url_matches if row.get("page_start") in source_pages]
            if page_matches:
                unique = {str(row.get("chunk_id")): row for row in page_matches if row.get("chunk_id")}
                return list(unique.values()), "exact", 1.0, "exact_source_page_mapping"
        unique = {str(row.get("chunk_id")): row for row in url_matches if row.get("chunk_id")}
        return list(unique.values()), "exact", 1.0, "exact_source_url"
    if not fact_statement.strip():
        fact_statement = fallback_query
    if not fact_statement.strip():
        return [], "unmapped", None, "no_fact_text"

    statement_norm = _norm_text(fact_statement)
    exact_text = [
        row for row in corpus
        if statement_norm and statement_norm in (
            normalized_text_index.get(str(row.get("chunk_id")), "") if normalized_text_index is not None
            else _norm_text(row.get("text"))
        )
    ]
    if exact_text:
        return exact_text[:5], "high_confidence", 1.0, "exact_fact_text"

    scored = [(_text_similarity(fact_statement, row, df, len(corpus), (terms_index or {}).get(str(row.get("chunk_id")))), row) for row in corpus]
    scored = [(score, row) for score, row in scored if score >= 0.30]
    scored.sort(key=lambda item: (-item[0], str(item[1].get("document_id") or ""), int(item[1].get("page_start") or 0), str(item[1].get("chunk_id") or "")))
    if not scored and fallback_query and _norm_text(fallback_query) != _norm_text(fact_statement):
        fallback_scored = [(_text_similarity(fallback_query, row, df, len(corpus), (terms_index or {}).get(str(row.get("chunk_id")))), row) for row in corpus]
        fallback_scored = [(score, row) for score, row in fallback_scored if score >= 0.30]
        fallback_scored.sort(key=lambda item: (-item[0], str(item[1].get("document_id") or ""), int(item[1].get("page_start") or 0), str(item[1].get("chunk_id") or "")))
        if fallback_scored:
            best_score = fallback_scored[0][0]
            status = "medium_confidence" if best_score >= 0.54 else "low_confidence"
            selected = [row for score, row in fallback_scored if score >= max(0.30, best_score - 0.08)][:3]
            return selected, status, round(best_score, 6), "lexical_similarity_fallback"
    if not scored:
        return [], "unmapped", None, "no_text_match"
    best_score = scored[0][0]
    if best_score >= 0.82 and len(_terms(fact_statement)) >= 5:
        status, method, limit = "high_confidence", "high_confidence_text_match", 3
    elif best_score >= 0.54:
        status, method, limit = "medium_confidence", "lexical_similarity_search", 3
    else:
        status, method, limit = "low_confidence", "lexical_similarity_search", 3
    selected = [row for score, row in scored if score >= max(0.30, best_score - 0.08)][:limit]
    return selected, status, round(best_score, 6), method


def _source_record(source_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "source_id": source_id,
        "organization": row.get("機關"),
        "document_title": row.get("文件／頁面") or row.get("文件/頁面"),
        "source_url": row.get("URL"),
        "reference_source": row.get("本題庫用途"),
        "page": row.get("頁碼") or row.get("頁次") or row.get("page") or row.get("page_number"),
        "source_status_in_workbook": row.get("核對狀態"),
    }


def _fact_record(fact_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "fact_id": fact_id,
        "topic": row.get("主題"),
        "statement": row.get("可核對事實（已改寫）") or row.get("可核對事實(已改寫)"),
        "core_value": row.get("核心數值"),
        "unit_or_range": row.get("單位／範圍") or row.get("單位/範圍"),
        "source_ids": _split_ids(row.get("來源ID")),
        "status_in_workbook": row.get("狀態"),
    }


def build_silver_questions(
    candidates: list[dict[str, Any]], corpus_rows: list[dict[str, Any]], *, root: str | Path = ROOT
) -> list[dict[str, Any]]:
    root = Path(root)
    retrieval_corpus = _eligible_corpus(corpus_rows)
    terms_index = {str(row.get("chunk_id")): _terms(row.get("text") or "") for row in retrieval_corpus if row.get("chunk_id")}
    normalized_text_index = {str(row.get("chunk_id")): _norm_text(row.get("text") or "") for row in retrieval_corpus if row.get("chunk_id")}
    df_counter: Counter[str] = Counter()
    for terms in terms_index.values():
        df_counter.update(terms)
    df = dict(df_counter)
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        source_by_id, fact_by_id = _workbook_reference(candidate, root)
        original = candidate.get("original_metadata") or {}
        source_ids = _split_ids(original.get("來源ID"))
        fact_ids = _split_ids(original.get("事實ID"))
        fact_ids.extend(
            fact_id for fact_id in _split_ids(original.get("必答重點事實ID")) if fact_id not in fact_ids
        )
        expected_facts = [_fact_record(fact_id, fact_by_id.get(fact_id)) for fact_id in fact_ids]
        expected_sources_by_id = {source_id: _source_record(source_id, source_by_id.get(source_id)) for source_id in source_ids}
        for fact in expected_facts:
            for source_id in fact.get("source_ids", []):
                expected_sources_by_id.setdefault(source_id, _source_record(source_id, source_by_id.get(source_id)))
        url = original.get("來源網址")
        if url and not any(source.get("source_url") == url for source in expected_sources_by_id.values()):
            expected_sources_by_id.setdefault("workbook_question_source", {
                "source_id": "workbook_question_source", "organization": None,
                "document_title": None, "source_url": url,
                "reference_source": "question row source URL", "source_status_in_workbook": None,
            })

        per_fact_mappings: list[dict[str, Any]] = []
        for fact in expected_facts:
            related = [source for source in expected_sources_by_id.values() if source.get("source_id") in fact.get("source_ids", [])]
            fallback_query = " ".join(str(value or "") for value in (
                candidate.get("question_candidate"), candidate.get("answer_candidate"),
                (candidate.get("original_metadata") or {}).get("主題"),
            ))
            mapped, status, score, method = _resolve_fact(
                fact, related, retrieval_corpus, df, fallback_query, terms_index, normalized_text_index
            )
            per_fact_mappings.append({
                "fact_id": fact.get("fact_id"),
                "mapping_status": status,
                "mapping_method": method,
                "mapping_score": score,
                "mapped_chunk_ids": [str(row.get("chunk_id")) for row in mapped if row.get("chunk_id")],
            })

        mapped_ids = list(dict.fromkeys(
            chunk_id for mapping in per_fact_mappings for chunk_id in mapping.get("mapped_chunk_ids", [])
        ))
        status_by_fact = [mapping["mapping_status"] for mapping in per_fact_mappings]
        if not mapped_ids:
            mapping_status = "unmapped"
        elif status_by_fact and all(status == "exact" for status in status_by_fact):
            mapping_status = "exact"
        elif status_by_fact and all(status in {"exact", "high_confidence"} for status in status_by_fact):
            mapping_status = "high_confidence"
        elif any(status == "medium_confidence" for status in status_by_fact):
            mapping_status = "medium_confidence"
        elif any(status == "high_confidence" for status in status_by_fact):
            mapping_status = "medium_confidence" if any(status == "unmapped" for status in status_by_fact) else "high_confidence"
        elif any(status == "low_confidence" for status in status_by_fact):
            mapping_status = "low_confidence"
        else:
            mapping_status = "unmapped"

        corpus_by_id = {str(row.get("chunk_id")): row for row in retrieval_corpus if row.get("chunk_id")}
        mapped_chunks = [
            {"chunk_id": chunk_id, "document_id": corpus_by_id[chunk_id].get("document_id"),
             "page": corpus_by_id[chunk_id].get("page_start"), "page_end": corpus_by_id[chunk_id].get("page_end")}
            for chunk_id in mapped_ids if chunk_id in corpus_by_id
        ]
        mapped_pages = sorted({
            (str(item["document_id"]), int(page))
            for item in mapped_chunks for page in range(int(item["page"] or 0), int(item["page_end"] or item["page"] or 0) + 1)
            if item.get("document_id") and item.get("page") is not None
        })
        mapped_documents = sorted({str(item["document_id"]) for item in mapped_chunks if item.get("document_id")})
        methods = list(dict.fromkeys(item["mapping_method"] for item in per_fact_mappings if item.get("mapped_chunk_ids")))
        scores = [float(item["mapping_score"]) for item in per_fact_mappings if item.get("mapping_score") is not None and item.get("mapped_chunk_ids")]
        results.append({
            "question_id": "silver_" + str(candidate.get("candidate_id") or "unknown"),
            "candidate_id": candidate.get("candidate_id"),
            "species_candidate": candidate.get("species"),
            "question": candidate.get("question_candidate"),
            "reference_answer": candidate.get("answer_candidate"),
            "category": candidate.get("category_candidate"),
            "question_type": candidate.get("question_type"),
            "difficulty_candidate": candidate.get("difficulty_candidate"),
            "risk_level": candidate.get("risk_level") if candidate.get("risk_level") in {"normal", "high"} else "normal",
            "source_workbook": candidate.get("source_workbook"),
            "source_sheet": candidate.get("source_sheet"),
            "source_row": candidate.get("source_row"),
            "expected_sources": list(expected_sources_by_id.values()),
            "expected_facts": expected_facts,
            "benchmark_type": "silver",
            "generation_source": "ai_question_bank",
            "question_origin": "ai_generated",
            "evidence_mapping_type": "auto_mapped",
            "mapping_backend": "lexical_only",
            "source_verification_status": "pending",
            "evidence_mapping_status": mapping_status,
            "mapping_method": methods or (["unmapped"] if mapping_status == "unmapped" else []),
            "mapping_score": round(min(scores), 6) if scores else None,
            "fact_mapping": per_fact_mappings,
            "mapped_chunks": mapped_chunks,
            "mapped_pages": [{"document_id": document_id, "page": page} for document_id, page in mapped_pages],
            "mapped_documents": mapped_documents,
            "mapping_note": "Automatic evidence proposal from Excel reference metadata and frozen retrieval corpus; not human Gold evidence.",
        })
    return results


def validate_silver_question(row: dict[str, Any]) -> list[str]:
    errors = [f"missing {field}" for field in SILVER_REQUIRED if field not in row]
    if row.get("benchmark_type") != "silver":
        errors.append("benchmark_type must be silver")
    if row.get("generation_source") != "ai_question_bank":
        errors.append("generation_source must be ai_question_bank")
    if row.get("question_origin") != "ai_generated":
        errors.append("question_origin must be ai_generated")
    if row.get("evidence_mapping_type") != "auto_mapped":
        errors.append("evidence_mapping_type must be auto_mapped")
    if row.get("mapping_backend") != "lexical_only":
        errors.append("mapping_backend must identify the non-embedding lexical mapper used in this run")
    if row.get("evidence_mapping_status") not in MAPPING_STATUSES:
        errors.append("invalid evidence_mapping_status")
    if row.get("risk_level") not in {"normal", "high"}:
        errors.append("risk_level must be normal or high")
    if not isinstance(row.get("mapped_chunks"), list) or not isinstance(row.get("mapped_documents"), list):
        errors.append("mapped_chunks and mapped_documents must be arrays")
    if row.get("evidence_mapping_status") == "unmapped" and row.get("mapped_chunks"):
        errors.append("unmapped question cannot have mapped_chunks")
    if row.get("evidence_mapping_status") in {"exact", "high_confidence", "medium_confidence", "low_confidence"} and not row.get("mapped_chunks"):
        errors.append("mapped status requires at least one mapped chunk")
    return errors


def coverage_report(questions: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row.get("evidence_mapping_status", "unknown") for row in questions)
    eligible_count = statuses["exact"] + statuses["high_confidence"]

    def grouped(field: str) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in questions:
            groups[str(row.get(field) or "unknown")].append(row)
        return {
            key: {
                "total": len(items),
                "mapping_status": dict(sorted(Counter(item.get("evidence_mapping_status", "unknown") for item in items).items())),
                "exact_high_confidence": sum(item.get("evidence_mapping_status") in {"exact", "high_confidence"} for item in items),
            }
            for key, items in sorted(groups.items())
        }

    return {
        "benchmark_type": "silver",
        "generation_source": "ai_question_bank",
        "question_origin": "ai_generated",
        "evidence_mapping_type": "auto_mapped",
        "semantic_mapping_backend": "unavailable_no_embedding_runtime",
        "total_questions": len(questions),
        "mapping_status": {status: statuses[status] for status in MAPPING_STATUSES},
        "exact_mapped": statuses["exact"],
        "high_confidence": statuses["high_confidence"],
        "medium_confidence": statuses["medium_confidence"],
        "low_confidence": statuses["low_confidence"],
        "unmapped": statuses["unmapped"],
        "primary_evaluable_questions": eligible_count,
        "mapping_coverage_rate": (len(questions) - statuses["unmapped"]) / len(questions) if questions else 0.0,
        "primary_evaluable_rate": eligible_count / len(questions) if questions else 0.0,
        "by_species": grouped("species_candidate"),
        "by_category": grouped("category"),
        "by_question_type": grouped("question_type"),
        "risk_distribution": dict(sorted(Counter(row.get("risk_level", "unknown") for row in questions).items())),
        "note": "Coverage measures automatic evidence mapping only. It is not human Gold coverage or answer correctness.",
    }


def build_silver_dataset(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    candidates = read_jsonl(root / "data" / "gold" / "question_bank_candidates.jsonl")
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    corpus_rows = read_jsonl(corpus_path)
    questions = build_silver_questions(candidates, corpus_rows, root=root)
    errors = [(row.get("question_id"), validate_silver_question(row)) for row in questions]
    errors = [(question_id, issues) for question_id, issues in errors if issues]
    if errors:
        raise ValueError(f"Silver question validation failed: {errors[:5]}")
    output = root / "data" / "evaluation" / "silver" / "questions_v1.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in questions), encoding="utf-8", newline="\n")
    corpus_sha = sha256_file(corpus_path)
    silver_sha = sha256_file(output)
    coverage = coverage_report(questions)
    manifest = {
        "dataset_id": "silver_questions_v1",
        "benchmark_type": "silver",
        "generation_source": "ai_question_bank",
        "question_origin": "ai_generated",
        "evidence_mapping_type": "auto_mapped",
        "mapping_backend": "lexical_only",
        "question_count": len(questions),
        "source_candidate_file": "data/gold/question_bank_candidates.jsonl",
        "source_candidate_sha256": sha256_file(root / "data" / "gold" / "question_bank_candidates.jsonl"),
        "evaluation_corpus_file": "data/evaluation/corpus_v1.jsonl",
        "evaluation_corpus_sha256": corpus_sha,
        "silver_dataset_sha256": silver_sha,
        "mapping_status_counts": coverage["mapping_status"],
        "note": "AI-generated Silver benchmark only; references and mappings are unverified and are not human Gold ground truth. No embedding runtime was available, so the final mapping fallback is lexical text similarity, not vector semantic search.",
    }
    write_json(root / "data" / "evaluation" / "silver" / "manifest_v1.json", manifest)
    write_json(root / "reports" / "evaluation" / "silver_coverage_v1.json", coverage)
    return {"questions": questions, "manifest": manifest, "coverage": coverage}


def build_silver_readiness(root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    questions_path = root / "data" / "evaluation" / "silver" / "questions_v1.jsonl"
    corpus_path = root / "data" / "evaluation" / "corpus_v1.jsonl"
    manifest_path = root / "data" / "evaluation" / "corpus_manifest.json"
    questions = read_jsonl(questions_path) if questions_path.exists() else []
    errors = [(row.get("question_id"), validate_silver_question(row)) for row in questions]
    errors = [(question_id, issues) for question_id, issues in errors if issues]
    corpus_sha = sha256_file(corpus_path) if corpus_path.exists() else None
    silver_sha = sha256_file(questions_path) if questions_path.exists() else None
    corpus_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest_corpus_sha = corpus_manifest.get("corpus_sha256") or corpus_manifest.get("evaluation_corpus_sha256")
    coverage = coverage_report(questions)
    exact_high = coverage["exact_mapped"] + coverage["high_confidence"]
    checksum_valid = bool(corpus_sha and (manifest_corpus_sha in (None, corpus_sha)))
    ready = bool(questions and checksum_valid and not errors and exact_high > 0 and all(row.get("evidence_mapping_status") in MAPPING_STATUSES for row in questions))
    report = {
        "benchmark_type": "silver",
        "generation_source": "ai_question_bank",
        "question_origin": "ai_generated",
        "evidence_mapping_type": "auto_mapped",
        "mapping_backend": "lexical_only",
        "silver_question_count": len(questions),
        "question_schema_valid": not errors,
        "invalid_question_count": len(errors),
        "evidence_mapping_completed": bool(questions) and all(row.get("evidence_mapping_status") in MAPPING_STATUSES for row in questions),
        "exact_questions": coverage["exact_mapped"],
        "high_confidence_questions": coverage["high_confidence"],
        "medium_confidence_questions": coverage["medium_confidence"],
        "low_confidence_questions": coverage["low_confidence"],
        "unmapped_questions": coverage["unmapped"],
        "primary_evaluable_questions": exact_high,
        "evaluation_corpus_sha256": corpus_sha,
        "evaluation_corpus_manifest_sha256": manifest_corpus_sha,
        "corpus_checksum_valid": checksum_valid,
        "silver_dataset_sha256": silver_sha,
        "silver_benchmark_ready": ready,
        "human_gold_readiness": "unchanged; see reports/evaluation/benchmark_readiness.json",
        "validation_errors": errors[:30],
        "note": "Readiness is for AI-generated Silver retrieval benchmarking; it does not assert reference answer correctness or source authority.",
    }
    write_json(root / "reports" / "evaluation" / "silver_benchmark_readiness.json", report)
    return report
