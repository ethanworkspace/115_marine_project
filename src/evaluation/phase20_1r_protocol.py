"""Readiness rules for the Phase 20.1R corpus and identity recovery gate.

This module contains no model scoring or benchmark execution. It deliberately
keeps source screening counts separate from question-ready evidence units.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
CATEGORIES = ("Fact", "Water Quality", "Disease", "Climate / Cold", "Safe Medication / Law", "Calculation")
NORMAL_CATEGORIES = frozenset({"Fact", "Water Quality", "Disease", "Climate / Cold"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
M3_BASE = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
M3_REPO = "bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF"
M3_FILE = "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def m3_identity_ready(manifest: dict[str, Any]) -> bool:
    """Require exact Llama lineage and a hashed Q4_K_M GGUF artifact."""
    return (
        manifest.get("candidate_model") == M3_BASE
        and manifest.get("base_model_source") == M3_BASE
        and manifest.get("source_repository") == M3_REPO
        and manifest.get("file_name") == M3_FILE
        and manifest.get("quantization") == "Q4_K_M"
        and manifest.get("architecture") == "llama"
        and manifest.get("artifact_size_bytes", 0) > 0
        and valid_sha256(manifest.get("artifact_sha256"))
        and valid_sha256(manifest.get("ollama_digest"))
        and manifest.get("runtime_smoke_pass") is True
        and manifest.get("context_8192_smoke_pass") is True
    )


def judge_is_independent(judge: dict[str, Any], candidates: Iterable[dict[str, Any]]) -> bool:
    digest = judge.get("artifact_digest")
    candidate_digests = {row.get("artifact_digest") for row in candidates}
    return valid_sha256(digest) and digest not in candidate_digests and judge.get("is_candidate") is False


def judge_calibration_ready(judge: dict[str, Any], calibration: dict[str, Any], candidates: Iterable[dict[str, Any]]) -> bool:
    return (
        judge_is_independent(judge, candidates)
        and calibration.get("target_outputs") == 30
        and calibration.get("first_pass_completed") == 30
        and calibration.get("second_pass_completed") == 30
        and calibration.get("first_pass_schema_parse_rate") == 1.0
        and calibration.get("second_pass_schema_parse_rate") == 1.0
        and calibration.get("technical_failure_count") == 0
        and calibration.get("completion_truncation_count") == 0
    )


def evidence_unit_ready(unit: dict[str, Any]) -> bool:
    required = ("evidence_unit_id", "species", "category", "fact_or_rule", "support_span", "chunk_id", "document_id", "page", "source_title", "source_status", "date_version", "checksum", "risk_level", "readiness_status", "human_reviewed")
    if any(unit.get(key) in (None, "", [], {}) for key in required):
        return False
    if unit["species"] not in SPECIES or unit["category"] not in CATEGORIES:
        return False
    if unit["readiness_status"] not in {"silver_ready", "verified_ready"}:
        return False
    if not isinstance(unit["page"], int) or not valid_sha256(unit["checksum"]):
        return False
    if unit.get("duplicate_fact") is True or unit.get("unsupported_interpolation") is True:
        return False
    if unit["category"] in NORMAL_CATEGORIES:
        return unit.get("source_in_evaluation_corpus") is True and unit.get("provenance_complete") is True and unit.get("species_mapping_valid") is True and unit.get("category_mapping_valid") is True
    if unit["category"] == "Safe Medication / Law":
        return high_risk_unit_ready(unit)
    if unit["category"] == "Calculation":
        return unit.get("calculation_verified") is True and unit.get("candidate_llm_authored_expected_answer") is False
    return False


def high_risk_unit_ready(unit: dict[str, Any]) -> bool:
    required = ("authority", "document_title", "page", "date_version", "applicability", "checksum")
    return (
        unit.get("category") == "Safe Medication / Law"
        and unit.get("readiness_status") == "verified_ready"
        and unit.get("official_source") is True
        and unit.get("source_status") == "verified"
        and unit.get("current_applicability_verified") is True
        and all(unit.get(key) not in (None, "") for key in required)
        and valid_sha256(unit.get("checksum"))
    )


def calculation_unit_ready(unit: dict[str, Any]) -> bool:
    required = ("calculation_unit_id", "species", "formula", "variables", "units", "valid_range", "expected_operation", "rounding_rule", "allowed_tolerance", "source_doc", "page", "checksum", "deterministic_expected_answer_source")
    return (
        all(unit.get(key) not in (None, "", [], {}) for key in required)
        and unit.get("species") in SPECIES
        and isinstance(unit.get("page"), int)
        and valid_sha256(unit.get("checksum"))
        and unit.get("candidate_llm_authored_expected_answer") is False
    )


def evidence_matrix(units: Iterable[dict[str, Any]], screening_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    seen: set[tuple[str, str, str]] = set()
    for unit in units:
        if not evidence_unit_ready(unit):
            continue
        key = (unit["species"], unit["category"], re.sub(r"\s+", "", unit["fact_or_rule"]).casefold())
        if key in seen:
            continue
        seen.add(key)
        counts[key[:2]] += 1
    scan = {(r.get("species"), r.get("category")): r for r in screening_rows}
    result = []
    for species in SPECIES:
        for category in CATEGORIES:
            n = counts[(species, category)]
            old = scan.get((species, category), {})
            result.append({
                "species": species,
                "category": category,
                "target_ready_units": 5,
                "ready_unit_count": n,
                "screening_candidate_chunk_count": old.get("screening_candidate_chunk_count", 0),
                "readiness_status": "ready" if n >= 5 else ("needs_review" if old.get("screening_candidate_chunk_count", 0) else "missing"),
                "screening_count_is_not_unit_or_question_count": True,
            })
    return result


def phase20_2_readiness(gates: dict[str, bool]) -> dict[str, Any]:
    required = ("four_models_ready", "independent_judge_ready", "normal_evidence_ready", "high_risk_ready", "calculation_ready", "final_corpus_ready", "e4_final_ready")
    failed = [key for key in required if gates.get(key) is not True]
    return {
        "phase20_2_benchmark_construction_ready": not failed,
        "gates": {key: gates.get(key) is True for key in required},
        "failed_gates": failed,
        "formal_four_model_scoring": False,
        "winner": None,
        "selection_requests_run": 0,
        "edge_requests_run": 0,
    }

