"""Validation helpers for Phase 20.1 readiness artifacts.

These helpers deliberately gate readiness on verified source units and exact
model artifacts. Candidate screening counts are retained as diagnostics only.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable


SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
CATEGORIES = (
    "Fact",
    "Water Quality",
    "Disease",
    "Climate / Cold",
    "Safe Medication / Law",
    "Calculation",
)
REVIEW_STATUSES = {"ready", "needs_review", "missing"}
UNIT_FIELDS = {
    "evidence_unit_id", "species", "category", "fact_or_rule", "chunk_id",
    "document_id", "page", "source_title", "source_type", "source_status",
    "date_version", "checksum", "risk_level", "review_status", "notes",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def candidate_identity_ready(row: dict[str, Any]) -> bool:
    """Require a verified source lineage and a content-addressed local artifact."""
    return (
        row.get("identity_verified") is True
        and valid_sha256(row.get("digest"))
        and valid_sha256(row.get("artifact_sha256"))
        and row.get("artifact_checksum_match") is True
        and row.get("lineage_verified") is True
        and row.get("architecture")
        and row.get("parameter_count")
        and row.get("quantization")
        and row.get("artifact_size_bytes")
        and row.get("context_length")
        and row.get("tokenizer_identity")
        and row.get("source_url")
    )


def judge_is_independent(judge_digest: str | None, candidate_digests: Iterable[str | None]) -> bool:
    return valid_sha256(judge_digest) and judge_digest not in {d for d in candidate_digests if d}


def judge_preflight_ready(report: dict[str, Any], candidate_digests: Iterable[str | None]) -> bool:
    if not judge_is_independent(report.get("judge_digest"), candidate_digests):
        return False
    return (
        report.get("calibration_target") == 30
        and report.get("first_pass_completed") == 30
        and report.get("second_pass_completed") == 30
        and report.get("schema_parse_rate") == 1.0
        and report.get("truncation_count") == 0
        and report.get("technical_failure_count") == 0
        and report.get("metrics_parseable") is True
    )


def evidence_unit_errors(unit: dict[str, Any]) -> list[str]:
    errors = sorted(UNIT_FIELDS - set(unit))
    if unit.get("species") not in SPECIES:
        errors.append("invalid_species")
    if unit.get("category") not in CATEGORIES:
        errors.append("invalid_category")
    if unit.get("review_status") not in REVIEW_STATUSES:
        errors.append("invalid_review_status")
    if unit.get("review_status") == "ready":
        for key in ("evidence_unit_id", "fact_or_rule", "chunk_id", "document_id", "source_title", "source_type", "source_status", "date_version", "notes"):
            if not unit.get(key):
                errors.append(f"ready_unit_missing_{key}")
        if not isinstance(unit.get("page"), int) or unit.get("page") < 0:
            errors.append("ready_unit_invalid_page")
        if not valid_sha256(unit.get("checksum")):
            errors.append("ready_unit_invalid_checksum")
    return errors


def evidence_matrix_ready(units: Iterable[dict[str, Any]], required_per_cell: int = 5) -> bool:
    counts: Counter[tuple[str, str]] = Counter()
    seen_ids: set[str] = set()
    normalized_facts: set[tuple[str, str, str]] = set()
    for unit in units:
        if evidence_unit_errors(unit):
            continue
        if unit.get("review_status") != "ready":
            continue
        unit_id = unit["evidence_unit_id"]
        if unit_id in seen_ids:
            return False
        seen_ids.add(unit_id)
        fact_key = (unit["species"], unit["category"], re.sub(r"\s+", "", unit["fact_or_rule"]).casefold())
        if fact_key in normalized_facts:
            return False
        normalized_facts.add(fact_key)
        counts[(unit["species"], unit["category"])] += 1
    return all(counts[(species, category)] >= required_per_cell for species in SPECIES for category in CATEGORIES)


def high_risk_unit_verified(unit: dict[str, Any]) -> bool:
    required = ("authority", "document_title", "page", "date_version", "applicability", "checksum")
    return (
        unit.get("category") == "Safe Medication / Law"
        and unit.get("review_status") == "ready"
        and unit.get("source_type") in {"official", "government", "official_government"}
        and unit.get("source_status") == "verified"
        and unit.get("current_applicability_verified") is True
        and all(unit.get(key) not in (None, "") for key in required)
        and valid_sha256(unit.get("checksum"))
    )


def calculation_registry_ready(units: Iterable[dict[str, Any]]) -> bool:
    rows = list(units)
    if len(rows) != 30:
        return False
    required = ("species", "formula", "variables", "units", "input_constraints", "expected_operation", "rounding_rule", "allowed_tolerance", "source_doc", "page", "checksum")
    per_species = Counter()
    ids: set[str] = set()
    for unit in rows:
        if any(unit.get(key) in (None, "", [], {}) for key in required):
            return False
        if unit["species"] not in SPECIES or not valid_sha256(unit["checksum"]):
            return False
        if not isinstance(unit["page"], int) or unit["page"] < 0:
            return False
        if not unit.get("deterministic_expected_answer_source") or unit.get("candidate_llm_authored_expected_answer") is not False:
            return False
        unit_id = unit.get("calculation_unit_id")
        if not unit_id or unit_id in ids:
            return False
        ids.add(unit_id)
        per_species[unit["species"]] += 1
    return all(per_species[species] == 5 for species in SPECIES)


def phase20_2_readiness(gates: dict[str, bool]) -> dict[str, Any]:
    required = (
        "model_identity_ready", "judge_ready", "evidence_matrix_ready",
        "high_risk_ready", "calculation_ready",
    )
    results = {key: gates.get(key) is True for key in required}
    failed = [key for key, passed in results.items() if not passed]
    return {
        "phase20_2_benchmark_construction_ready": not failed,
        "requirements": results,
        "failed_gates": failed,
        "formal_ranking_run": False,
        "winner": None,
        "selection_outputs_run": False,
    }


def empty_evidence_matrix(scan_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve source scan counts; never infer question-ready units from chunks."""
    by_cell = {(row["species"], row["category"]): row for row in scan_rows}
    matrix: list[dict[str, Any]] = []
    for species in SPECIES:
        for category in CATEGORIES:
            old = by_cell.get((species, category), {})
            matrix.append({
                "species": species,
                "category": category,
                "target_ready_units": 5,
                "ready_unit_count": 0,
                "screening_candidate_chunk_count": old.get("screening_candidate_chunk_count", 0),
                "prior_scan_status": old.get("status", "not_screened"),
                "status": "missing" if old.get("status") == "no_screened_chunk" else "needs_review",
                "question_capacity_confirmed": False,
                "count_semantics": "source_chunk_screening_only_not_evidence_unit_or_question_count",
            })
    return matrix
