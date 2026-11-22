from __future__ import annotations

import hashlib

from scripts.evaluation.build_phase20_1e_step2 import (
    CATEGORIES,
    SPECIES,
    candidate_unit_from_span,
    exact_candidate_fingerprint,
    extract_literal_formula,
    make_pool_candidate,
    normalize_fact,
)


def _valid_pair(text: str = "烏魚屬溫熱帶淺海中上層魚類。"):
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_digest = "a" * 64
    document_id = "doc-1"
    row = {
        "chunk_id": "chunk-1", "document_id": document_id, "document_title": "烏魚養殖技術手冊",
        "page": 3, "text": text, "content_checksum": digest, "source_checksum": source_digest,
        "source_verification_status": "verified", "source_verified": True,
        "evidence_quality_status": "accepted", "extraction_confidence": 0.95,
        "warnings": [], "quality_reasons": [], "risk_level": "normal", "species": "烏魚", "category": "fact",
        "source_span": [{"document_id": document_id, "page_number": 3, "start_position": 0,
                         "end_position": len(text), "text_checksum": digest}],
    }
    corpus = {
        "chunk_id": "chunk-1", "document_id": document_id, "text": text, "content_checksum": digest,
        "source_verification_status": "verified", "ingestion_status": "accepted", "retrieval_role": "retrieval",
        "duplicate_status": "none", "chunk_version": "corpus-v2",
    }
    return row, corpus


def test_evidence_unit_schema_and_exact_support_span():
    row, corpus = _valid_pair()
    unit = candidate_unit_from_span(row, corpus, "烏魚", "Fact", "烏魚屬溫熱帶淺海中上層魚類")
    assert unit is not None
    assert unit["readiness_status"] == "silver_ready"
    assert unit["human_reviewed"] is False
    assert unit["support_span"] in row["text"]
    assert unit["checksum"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
    assert all(k in unit for k in ("evidence_unit_id", "species", "category", "risk_level", "atomic_fact_or_rule", "chunk_id", "document_id", "page", "source_title", "source_status", "source_version", "applicability", "duplicate_group_id", "verification_method", "rejection_reason"))


def test_unit_must_not_invent_or_rewrite_fact():
    row, corpus = _valid_pair()
    fabricated = "烏魚在冬季最適水溫為20℃"
    assert fabricated not in row["text"]
    assert candidate_unit_from_span(row, corpus, "烏魚", "Fact", fabricated) is None


def test_invalid_provenance_and_checksum_do_not_promote():
    row, corpus = _valid_pair()
    row["content_checksum"] = "0" * 64
    candidate = make_pool_candidate(row, {"chunk-1": corpus})
    assert candidate["candidate_processing_status"] == "rejected"
    assert "content_checksum_does_not_match_text" in candidate["reasons"]
    assert candidate_unit_from_span(row, corpus, "烏魚", "Fact", "烏魚屬溫熱帶淺海中上層魚類") is None


def test_species_and_category_must_be_supported_in_same_span():
    row, corpus = _valid_pair()
    assert candidate_unit_from_span(row, corpus, "吳郭魚", "Fact", "烏魚屬溫熱帶淺海中上層魚類") is None
    assert candidate_unit_from_span(row, corpus, "烏魚", "Disease", "烏魚屬溫熱帶淺海中上層魚類") is None


def test_high_risk_rule_cannot_use_normal_silver_promotion():
    row, corpus = _valid_pair()
    row["risk_level"] = "high"
    assert candidate_unit_from_span(row, corpus, "烏魚", "Fact", "烏魚屬溫熱帶淺海中上層魚類") is None


def test_repeated_fact_fingerprint_is_stable_and_numeric_sensitive():
    first = exact_candidate_fingerprint("烏魚", "Fact", "烏魚屬溫熱帶魚類。")
    same = exact_candidate_fingerprint("烏魚", "Fact", "烏魚 屬溫熱帶魚類")
    changed = exact_candidate_fingerprint("烏魚", "Fact", "烏魚屬亞熱帶魚類")
    assert first == same
    assert first != changed
    assert normalize_fact("FCR = 1.2") != normalize_fact("FCR = 1.3")


def test_formula_extraction_is_literal_and_does_not_create_gold():
    text = "飼料係數（FCR）= 飼料投餵量 / 魚體增重量。"
    assert extract_literal_formula(text) == "FCR）= 飼料投餵量 / 魚體增重量"
    # The registry records formulas only as candidates; no numeric expected answer is authored here.


def test_matrix_taxonomy_has_six_species_and_categories():
    assert len(SPECIES) == 6
    assert len(CATEGORIES) == 6
    assert len(SPECIES) * len(CATEGORIES) == 36
