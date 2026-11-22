"""Conservative, deterministic Phase 20.1E Step 2 corpus audit.

This script reads only frozen Evaluation Corpus v2 and the existing screening
pool. It never fetches or writes source/corpus/index/model/database artifacts.
All generated files are confined to the new execution report directory.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2_existing_corpus"
POOL_PATH = ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"
CORPUS_PATH = ROOT / "data/evaluation/corpus_v2.jsonl"
PHASE20_GAPS = ROOT / "reports/evaluation/final_model_selection/phase20/evidence_coverage_gaps.json"
PHASE20_MATRIX = ROOT / "reports/evaluation/final_model_selection/phase20_1R/evidence_matrix.json"
R1_READINESS = ROOT / "reports/evaluation/final_model_selection/phase20_1R/readiness.json"
HISTORICAL_PRODUCTION_SMOKE = ROOT / "reports/evaluation/final_model_selection/phase20_1/production_compatibility.json"
R3_BASELINE = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/baseline_integrity.json"
STEP0 = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/environment_preflight.json"
DB_PATH = ROOT / "rag_store.sqlite3"

SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
CATEGORIES = ("Fact", "Water Quality", "Disease", "Climate / Cold", "Safe Medication / Law", "Calculation")
NORMAL_CATEGORIES = {
    "fact": "Fact", "water_quality": "Water Quality", "disease": "Disease", "climate": "Climate / Cold"
}
CORPUS_CATEGORY = {v: k for k, v in NORMAL_CATEGORIES.items()}
FORMULA_CUE = re.compile(r"計算式|公式|SGR|FCR|每立方公尺|每公斤|%\s*/\s*day|×|÷|ppm|投餌量", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
BAD_TEXT_RE = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")
SENTENCE_SPLIT = re.compile(r"[。！？；;\r\n]+")
CLAUSE_SPLIT = re.compile(r"[，,]+")
CATEGORY_MARKERS = {
    "Fact": re.compile(r"為|是|屬|分布|原產|魚種|魚類|廣鹽|廣溫|繁殖|生長|體型|經濟物種"),
    "Water Quality": re.compile(r"水溫|水質|鹽度|溶氧|酸鹼|氨氮|亞硝酸|鹼度|硬度|水深|換水|pH|psu|ppm|℃" , re.I),
    "Disease": re.compile(r"疾病|病原|感染|症狀|病魚|寄生蟲|病害|防治|疫病|病毒|細菌|水黴|潰爛"),
    "Climate / Cold": re.compile(r"寒流|低溫|高溫|冬季|夏季|颱風|氣候|冷|熱緊迫|溫度下降|降溫|驟降|攝氏|℃"),
}
COMPOUND_MARKER = re.compile(r"以及|並且|同時|分別|包括|或者|因此|所以|然而|但是|且|並|或|及|與|但")
ASSERTION_MARKER = re.compile(r"為|是|屬|可|能|會|有|需|應|建議|分布|生存|生長|具有|主要|最低|最高|範圍")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def frozen_phase15_20_snapshot() -> dict[str, str]:
    # Reuse the Phase 20 preflight's frozen path definition without invoking its writer.
    from importlib.util import module_from_spec, spec_from_file_location
    module_path = ROOT / "scripts/phase20_preflight.py"
    spec = spec_from_file_location("phase20_preflight_readonly", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frozen Phase 20 protected-file definition")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in module.protected_files()}


def make_pool_candidate(row: dict[str, Any], corpus_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cid = str(row.get("chunk_id") or "")
    corpus = corpus_by_id.get(cid)
    text = str(row.get("text") or "")
    errors: list[str] = []
    if corpus is None:
        errors.append("chunk_missing_from_evaluation_corpus")
    else:
        if row.get("document_id") != corpus.get("document_id"):
            errors.append("document_id_mismatch")
        if row.get("content_checksum") != corpus.get("content_checksum"):
            errors.append("declared_content_checksum_mismatch")
        actual_hash = sha256_bytes(text.encode("utf-8"))
        if row.get("content_checksum") != actual_hash or corpus.get("content_checksum") != actual_hash:
            errors.append("content_checksum_does_not_match_text")
        if row.get("text") != corpus.get("text"):
            errors.append("pool_text_differs_from_corpus_text")
    if not row.get("document_id") or not row.get("document_title"):
        errors.append("document_provenance_missing")
    if not isinstance(row.get("page"), int) or row.get("page", 0) < 1:
        errors.append("page_provenance_missing")
    if not SHA256_RE.fullmatch(str(row.get("source_checksum") or "")):
        errors.append("source_checksum_missing_or_invalid")
    spans = row.get("source_span") or []
    matching_span = any(
        s.get("document_id") == row.get("document_id")
        and s.get("page_number") == row.get("page")
        and isinstance(s.get("start_position"), int)
        and isinstance(s.get("end_position"), int)
        and s.get("end_position") >= s.get("start_position")
        and s.get("text_checksum") == row.get("content_checksum")
        for s in spans if isinstance(s, dict)
    )
    if not matching_span:
        errors.append("source_span_provenance_incomplete")
    if row.get("evidence_quality_status") != "accepted":
        errors.append(f"screening_quality_{row.get('evidence_quality_status') or 'missing'}")
    if row.get("source_verified") is not True or row.get("source_verification_status") != "verified":
        errors.append("source_verification_not_verified")
    if corpus and corpus.get("ingestion_status") != "accepted":
        errors.append("corpus_ingestion_not_accepted")
    if corpus and corpus.get("retrieval_role") != "retrieval":
        errors.append("not_retrieval_eligible")
    if corpus and corpus.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
        errors.append("corpus_duplicate_not_canonical")
    if row.get("warnings"):
        errors.append("screening_warnings_present")
    if row.get("quality_reasons"):
        errors.append("quality_reasons_present")
    if BAD_TEXT_RE.search(text):
        errors.append("text_contains_replacement_or_control_characters")
    if len(text.strip()) < 100:
        errors.append("text_below_100_character_quality_gate")
    if len(text) > 6000:
        errors.append("text_above_6000_character_quality_gate")
    if not isinstance(row.get("extraction_confidence"), (int, float)) or row.get("extraction_confidence", 0) < 0.8:
        errors.append("extraction_confidence_below_0_8")

    species = row.get("species")
    category = NORMAL_CATEGORIES.get(row.get("category"))
    if species not in SPECIES:
        errors.append("species_unassigned_or_unrecognized")
    if category is None:
        errors.append("category_unassigned_or_outside_normal_target")
    if species in SPECIES and species not in text:
        errors.append("species_not_explicit_in_support_text")
    if species in SPECIES and any(other in text for other in SPECIES if other != species):
        errors.append("multiple_target_species_in_chunk_applicability_ambiguous")

    irrecoverable = {
        "chunk_missing_from_evaluation_corpus", "content_checksum_does_not_match_text",
        "pool_text_differs_from_corpus_text", "text_contains_replacement_or_control_characters",
        "source_checksum_missing_or_invalid", "source_span_provenance_incomplete",
    }
    if row.get("evidence_quality_status") == "rejected":
        irrecoverable.add("screening_quality_rejected")
    if corpus and corpus.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
        irrecoverable.add("corpus_duplicate_not_canonical")
    return {
        "candidate_id": cid or None,
        "original_id": cid or None,
        "source": {
            "document_id": row.get("document_id"), "source_title": row.get("document_title"),
            "page": row.get("page"), "source_checksum": row.get("source_checksum"),
            "content_checksum": row.get("content_checksum"),
        },
        "original_species": species,
        "original_category": row.get("category"),
        "species_category_assignment": {"species": species if species in SPECIES else None, "category": category},
        "original_screening_status": row.get("evidence_quality_status"),
        "source_verification_status": row.get("source_verification_status"),
        "risk_level": row.get("risk_level"),
        "candidate_processing_status": "rejected" if irrecoverable.intersection(errors) else "needs_review",
        "promotion_status": "not_promoted",
        "reasons": errors or ["candidate_screened_but_no_independently_verified_atomic_unit_extracted"],
        "unit_ids": [],
    }


def normalize_fact(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,。！？；;：:、\"'「」『』（）()\[\]【】]", "", text)
    return text.casefold()


def exact_candidate_fingerprint(species: str, category: str, fact: str) -> str:
    return sha256_bytes(f"{species}|{category}|{normalize_fact(fact)}".encode("utf-8"))


def classify_clause(clause: str) -> str | None:
    matched = [category for category, pattern in CATEGORY_MARKERS.items() if pattern.search(clause)]
    # Temperature/degree notation by itself is not enough to distinguish a water-quality
    # fact from a seasonal/climate claim; require a non-overlapping cue.
    if "Water Quality" in matched and "Climate / Cold" in matched:
        water_specific = re.search(r"水溫|水質|鹽度|溶氧|氨氮|亞硝酸|水深|換水|psu|ppm|pH", clause, re.I)
        climate_specific = re.search(r"寒流|冬季|夏季|颱風|氣候|熱緊迫|溫度下降|降溫|驟降", clause)
        if water_specific and not climate_specific:
            matched.remove("Climate / Cold")
        elif climate_specific and not water_specific:
            matched.remove("Water Quality")
    if len(matched) != 1:
        return None
    return matched[0]


def candidate_unit_from_span(row: dict[str, Any], corpus: dict[str, Any], species: str, category: str, span: str) -> dict[str, Any] | None:
    """Promote only a literal, self-contained proposition that clears all deterministic gates."""
    text = str(row.get("text") or "")
    if row.get("risk_level") != "normal":
        return None
    if row.get("evidence_quality_status") != "accepted" or row.get("source_verified") is not True or row.get("source_verification_status") != "verified":
        return None
    if corpus.get("ingestion_status") != "accepted" or corpus.get("retrieval_role") != "retrieval" or corpus.get("source_verification_status") != "verified":
        return None
    if corpus.get("duplicate_status") in {"exact_duplicate", "duplicate_source"}:
        return None
    if row.get("warnings") or row.get("quality_reasons") or BAD_TEXT_RE.search(text):
        return None
    if not isinstance(row.get("extraction_confidence"), (int, float)) or row["extraction_confidence"] < 0.8:
        return None
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != row.get("content_checksum") or row.get("content_checksum") != corpus.get("content_checksum"):
        return None
    if species not in span or any(other in span for other in SPECIES if other != species):
        return None
    if classify_clause(span) != category or not ASSERTION_MARKER.search(span):
        return None
    if len(span) < 12 or len(span) > 150 or COMPOUND_MARKER.search(span) or "、" in span or re.search(r"[：:]", span):
        return None
    if re.search(r"用藥|藥劑|劑量|停藥|抗生素|投藥", span):
        return None
    if not row.get("document_id") or not isinstance(row.get("page"), int) or row.get("page", 0) < 1:
        return None
    if not SHA256_RE.fullmatch(str(row.get("source_checksum") or "")):
        return None
    source_spans = row.get("source_span") or []
    if not any(s.get("document_id") == row.get("document_id") and s.get("page_number") == row.get("page") and s.get("text_checksum") == row.get("content_checksum") for s in source_spans if isinstance(s, dict)):
        return None
    start = text.find(span)
    if start < 0:
        return None
    fingerprint = exact_candidate_fingerprint(species, category, span)
    unit_id = "eu_" + fingerprint[:24]
    return {
        "evidence_unit_id": unit_id, "species": species, "category": category, "risk_level": "normal",
        "atomic_fact_or_rule": span, "support_span": span, "support_start": start, "support_end": start + len(span),
        "chunk_id": row.get("chunk_id"), "document_id": row.get("document_id"), "page": row.get("page"),
        "source_title": row.get("document_title"), "source_status": row.get("source_verification_status"),
        "source_version": corpus.get("chunk_version"), "checksum": row.get("content_checksum"),
        "source_checksum": row.get("source_checksum"), "applicability": "specific_species_explicit_in_support_span",
        "duplicate_group_id": fingerprint, "readiness_status": "silver_ready",
        "verification_method": "deterministic_exact_source_substring_checksum_provenance_species_and_single_category_rule",
        "human_reviewed": False, "rejection_reason": None,
    }


def extract_atomic_candidate_units(row: dict[str, Any], corpus: dict[str, Any], species: str, category: str) -> list[dict[str, Any]]:
    text = str(row.get("text") or "")
    out = []
    for sentence in SENTENCE_SPLIT.split(text):
        for clause in CLAUSE_SPLIT.split(sentence):
            span = re.sub(r"\s+", " ", clause).strip(" \t\u3000·•-—")
            unit = candidate_unit_from_span(row, corpus, species, category, span)
            if unit:
                out.append(unit)
    return out


def explicit_reclassification(row: dict[str, Any]) -> tuple[str, str] | None:
    """Allow unmapped rows only when one species and one direct category cue coexist in one clause."""
    if row.get("evidence_quality_status") != "accepted" or row.get("source_verified") is not True or row.get("warnings") or row.get("quality_reasons"):
        return None
    text = str(row.get("text") or "")
    species_hits = [s for s in SPECIES if s in text]
    if len(species_hits) != 1:
        return None
    target_species = species_hits[0]
    matched = set()
    for sentence in SENTENCE_SPLIT.split(text):
        for clause in CLAUSE_SPLIT.split(sentence):
            if target_species in clause:
                kind = classify_clause(clause)
                if kind:
                    matched.add(kind)
    if len(matched) == 1:
        return target_species, next(iter(matched))
    return None


def source_candidate_coverage(corpus: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
    retrieval = [r for r in corpus if r.get("retrieval_role") == "retrieval" and r.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}]
    high: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    calc: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for species in SPECIES:
        for row in retrieval:
            text_title = f"{row.get('text') or ''} {row.get('source_title') or ''}"
            if species not in text_title:
                continue
            if (row.get("risk_level") == "high" and row.get("source_verification_status") == "verified"
                    and row.get("source_verified") is True and row.get("legal_status") == "current"
                    and row.get("source_id") == "moa_official"):
                high[(species, "Safe Medication / Law")].append(row)
            if FORMULA_CUE.search(row.get("text") or ""):
                calc[(species, "Calculation")].append(row)
    return high, calc


def extract_literal_formula(text: str) -> str | None:
    patterns = [
        re.compile(r"(?:FCR|SGR)[）)]?\s*(?:=|：|:|為)\s*[^。；;\n]{1,120}", re.I),
        re.compile(r"(?:計算式|公式)\s*[:：]?\s*[^。；;\n]{1,120}"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


def build_step2() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing Step 2 output directory: {OUT}")
    step0 = read_json(STEP0)
    baseline = read_json(R3_BASELINE)
    r1 = read_json(R1_READINESS)
    if not step0.get("phase20_1E_environment_ready") or not baseline.get("phase20_1E_baseline_integrity_pass"):
        raise RuntimeError("Phase 20.1E Step 0/1 baseline is not passing")
    if not baseline.get("overall_integrity_pass"):
        raise RuntimeError("baseline_integrity.json overall_integrity_pass is false")

    pool_bytes = POOL_PATH.read_bytes()
    corpus_bytes = CORPUS_PATH.read_bytes()
    pool = read_jsonl(POOL_PATH)
    corpus = read_jsonl(CORPUS_PATH)
    prior_scan = read_json(PHASE20_GAPS)
    prior_scan_assignment_sum = sum(int(x.get("screening_candidate_chunk_count", 0) or 0) for x in prior_scan.get("matrix", []))
    pool_sha, corpus_sha = sha256_bytes(pool_bytes), sha256_bytes(corpus_bytes)
    expected_corpus = next((x.get("expected") for x in baseline.get("checks", []) if x.get("name") == "Evaluation_Corpus_v2"), None)
    if expected_corpus != corpus_sha:
        raise RuntimeError(f"Evaluation Corpus v2 checksum mismatch: baseline={expected_corpus}, actual={corpus_sha}")
    if len(pool) != 486:
        raise RuntimeError(f"unexpected evidence-pool row count: {len(pool)}")
    corpus_by_id = {r.get("chunk_id"): r for r in corpus}
    if len(corpus_by_id) != len(corpus):
        raise RuntimeError("Evaluation Corpus contains duplicate chunk_id values")
    retrieval_count = sum(r.get("retrieval_role") == "retrieval" for r in corpus)
    if retrieval_count != 2224:
        raise RuntimeError(f"unexpected retrieval-eligible corpus count: {retrieval_count}")

    protected_before = frozen_phase15_20_snapshot()
    phase20_1_dir = ROOT / "reports/evaluation/final_model_selection/phase20_1"
    phase20_1_before = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in phase20_1_dir.rglob("*") if p.is_file()}
    step0_sha, baseline_sha = sha256_file(STEP0), sha256_file(R3_BASELINE)
    db_before = {"size_bytes": DB_PATH.stat().st_size, "mtime_ns": DB_PATH.stat().st_mtime_ns, "sha256": sha256_file(DB_PATH)}
    expected_db = baseline.get("database", {})
    expected_db_normalized = {
        "size_bytes": expected_db.get("size_bytes", expected_db.get("size")),
        "mtime_ns": expected_db.get("mtime_ns"),
        "sha256": expected_db.get("sha256"),
    }
    if db_before != expected_db_normalized:
        raise RuntimeError("rag_store.sqlite3 no longer matches Phase 20.1R baseline")

    candidates = [make_pool_candidate(row, corpus_by_id) for row in pool]
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    pool_rows_by_id = {row["chunk_id"]: row for row in pool}
    # Metadata-only assignments are not expanded. Reclassification is attempted only
    # for accepted/verified rows whose exact text contains one species and one category cue.
    reclassified_count = 0
    proposal_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        source_row = pool_rows_by_id[candidate["candidate_id"]]
        assignment = candidate["species_category_assignment"]
        species, category = assignment.get("species"), assignment.get("category")
        if not species or not category:
            reassigned = explicit_reclassification(source_row)
            if reassigned:
                species, category = reassigned
                candidate["species_category_assignment"] = {"species": species, "category": category}
                candidate["reclassified_from_original_metadata"] = True
                candidate["reclassification_method"] = "explicit_species_and_single_category_cue_in_same_literal_clause"
                candidate["reasons"] = [x for x in candidate["reasons"] if x not in {"species_unassigned_or_unrecognized", "category_unassigned_or_outside_normal_target"}]
                reclassified_count += 1
        if species in SPECIES and category in NORMAL_CATEGORIES.values():
            units = extract_atomic_candidate_units(source_row, corpus_by_id.get(candidate["candidate_id"], {}), species, category)
            for unit in units:
                proposal_groups[unit["duplicate_group_id"]].append(unit)
            if not units:
                candidate["reasons"].append("no_exact_atomic_source_span_passed_direct_support_and_category_checks")

    duplicate_unit_groups = []
    evidence_units: list[dict[str, Any]] = []
    unit_candidates_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fingerprint, units in sorted(proposal_groups.items()):
        units.sort(key=lambda u: (str(u.get("chunk_id")), u["support_start"]))
        primary = units[0]
        unit_candidates_by_chunk[str(primary["chunk_id"])].append(primary)
        evidence_units.append(primary)
        if len(units) > 1:
            duplicate_unit_groups.append({
                "duplicate_group_id": fingerprint, "fingerprint": fingerprint,
                "basis": "same normalized literal atomic proposition within species/category",
                "unit_count_before_dedup": len(units), "kept_evidence_unit_id": primary["evidence_unit_id"],
                "excluded_evidence_unit_ids": [u["evidence_unit_id"] for u in units[1:]],
                "candidate_chunk_ids": [u["chunk_id"] for u in units],
                "duplicate_count_excluded": len(units)-1,
            })
            for dupe in units[1:]:
                duplicate_candidate = candidate_by_id.get(str(dupe["chunk_id"]))
                if duplicate_candidate:
                    duplicate_candidate["candidate_processing_status"] = "duplicate"
                    duplicate_candidate["promotion_status"] = "duplicate_excluded"
                    duplicate_candidate["reasons"].append("same_normalized_atomic_proposition_already_counted")
        primary_candidate = candidate_by_id.get(str(primary["chunk_id"]))
        if primary_candidate:
            primary_candidate["candidate_processing_status"] = "silver_ready"
            primary_candidate["promotion_status"] = "promoted_silver_ready"
            primary_candidate["unit_ids"].append(primary["evidence_unit_id"])
    for candidate in candidates:
        if candidate["candidate_processing_status"] not in {"rejected", "duplicate", "silver_ready"}:
            candidate["candidate_processing_status"] = "needs_review"

    candidate_by_id = {row["candidate_id"]: row for row in candidates}

    # Duplicate audit: exact text duplicates within a proposed cell only. Similarity is not
    # promoted to a fact-level duplicate without semantic review.
    fingerprint_groups: dict[str, list[str]] = defaultdict(list)
    for row in pool:
        species, category = row.get("species"), NORMAL_CATEGORIES.get(row.get("category"))
        if species in SPECIES and category:
            fp = exact_candidate_fingerprint(species, category, str(row.get("text") or ""))
            fingerprint_groups[fp].append(str(row.get("chunk_id")))
    duplicate_groups = [
        {"duplicate_group_id": "exact_" + fp[:16], "fingerprint": fp, "basis": "normalized_exact_text_within_species_category", "candidate_ids": sorted(ids), "duplicate_count_excluded": len(ids)-1}
        for fp, ids in fingerprint_groups.items() if len(ids) > 1
    ]
    for group in duplicate_groups:
        ordered = group["candidate_ids"]
        for cid in ordered[1:]:
            candidate = candidate_by_id.get(cid)
            if candidate and candidate["candidate_processing_status"] == "needs_review":
                candidate["candidate_processing_status"] = "duplicate"
                candidate["promotion_status"] = "duplicate_excluded"
                candidate["reasons"].append("exact_normalized_candidate_text_already_screened_in_same_cell")

    high_candidates, calc_candidates = source_candidate_coverage(corpus)
    high_rows: list[dict[str, Any]] = []
    for cell, rows in sorted(high_candidates.items()):
        species, category = cell
        for row in rows:
            high_rows.append({
                "candidate_id": row.get("chunk_id"), "species": species, "category": category,
                "document_id": row.get("document_id"), "page": row.get("page_start"),
                "source_title": row.get("source_title"), "source_id": row.get("source_id"),
                "source_status": row.get("source_verification_status"), "legal_status": row.get("legal_status"),
                "source_checksum": row.get("source_checksum"), "content_checksum": row.get("content_checksum"),
                "exact_candidate_text": row.get("text"), "official_authority": "Ministry of Agriculture (corpus source_id=moa_official)",
                "applicability": "unknown", "readiness_status": "needs_review", "verified_ready": False,
                "review_blockers": ["species_specific_current_applicability_not_item_verified", "exact_rule_scope_and_effective_version_not_independently_confirmed_for_this_unit"],
                "medication_dose_or_withdrawal_advice_generated": False,
            })

    formula_registry: list[dict[str, Any]] = []
    formula_fingerprints: dict[str, list[str]] = defaultdict(list)
    for (species, _cat), rows in sorted(calc_candidates.items()):
        for row in rows:
            cid = str(row.get("chunk_id"))
            formula_literal = extract_literal_formula(str(row.get("text") or ""))
            fid = f"candidate_{species}_{cid}"
            normalized = normalize_fact(formula_literal or "")
            ffp = sha256_bytes(f"{species}|{normalized}".encode("utf-8")) if normalized else None
            if ffp:
                formula_fingerprints[ffp].append(fid)
            reasons = ["candidate_cue_only_not_verified_formula_unit"]
            if not formula_literal:
                reasons.append("no_explicit_formula_expression_extracted")
            if row.get("source_verification_status") != "verified" or row.get("source_verified") is not True:
                reasons.append("formula_source_not_verified")
            # Full range, assumptions, rounding, and tolerance are intentionally not inferred.
            formula_registry.append({
                "formula_id": fid, "record_type": "screening_candidate", "species": species,
                "calculation_type": "unclassified_candidate", "formula": formula_literal,
                "variables": [], "input_units": None, "output_unit": None, "valid_range": None,
                "assumptions": None, "rounding_rule": None, "allowed_tolerance": None,
                "source_document": row.get("document_id"), "source_title": row.get("source_title"),
                "source_page": row.get("page_start"), "chunk_id": cid,
                "support_span": formula_literal, "checksum": row.get("content_checksum"),
                "formula_fingerprint": ffp, "readiness_status": "needs_review", "verification_status": "needs_review",
                "gold_numeric_answer": None, "candidate_llm_or_judge_used_for_gold": False,
                "validation_reasons": reasons,
            })
    formula_dupes = [
        {"formula_duplicate_group_id": "formula_" + fp[:16], "fingerprint": fp, "candidate_formula_ids": sorted(ids), "duplicate_count_excluded": len(ids)-1, "basis": "same species and normalized literal formula; candidate-only, not counted as verified units"}
        for fp, ids in formula_fingerprints.items() if len(ids) > 1
    ]

    # Screening assignment counts include all mapped candidates, not just accepted ones.
    cell_candidate_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in pool:
        candidate = candidate_by_id[str(row.get("chunk_id"))]
        species = candidate.get("species_category_assignment", {}).get("species")
        category = candidate.get("species_category_assignment", {}).get("category")
        if species in SPECIES and category:
            cell_candidate_ids[(species, category)].append(str(row.get("chunk_id")))
    for cell, rows in calc_candidates.items():
        cell_candidate_ids[cell].extend(str(r.get("chunk_id")) for r in rows)
    for cell, rows in high_candidates.items():
        cell_candidate_ids[cell].extend(str(r.get("chunk_id")) for r in rows)

    matrix = []
    gap_registry = []
    candidate_status_by_cell: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for cell, ids in cell_candidate_ids.items():
        for cid in ids:
            if cell[1] == "Safe Medication / Law":
                candidate_status_by_cell[cell]["needs_review"] += 1
            elif cell[1] == "Calculation":
                candidate_status_by_cell[cell]["needs_review"] += 1
            else:
                status = candidate_by_id.get(cid, {}).get("candidate_processing_status", "needs_review")
                candidate_status_by_cell[cell][status] += 1

    for species in SPECIES:
        for category in CATEGORIES:
            cell = (species, category)
            ids = cell_candidate_ids.get(cell, [])
            counts = candidate_status_by_cell.get(cell, Counter())
            units = [u for u in evidence_units if u["species"] == species and u["category"] == category]
            silver = sum(u["readiness_status"] == "silver_ready" for u in units)
            verified = sum(u["readiness_status"] == "verified_ready" for u in units)
            ready = silver + verified
            all_reasons = []
            for cid in ids:
                if cid in candidate_by_id:
                    all_reasons.extend(candidate_by_id[cid]["reasons"])
            reason_counts = Counter(all_reasons)
            if not ids:
                missing_type = "no_candidate_in_current_corpus"
                status_reason = "current corpus has no screened candidate for this cell"
            elif category == "Calculation":
                missing_type = "formula_candidate_cue_without_complete_verified_formula"
                status_reason = "formula-cue chunks exist, but no formula unit has verified variables, units, valid range, assumptions, rounding, tolerance and source support"
            elif category == "Safe Medication / Law":
                missing_type = "official_candidate_requires_item_level_scope_and_currency_review"
                status_reason = "official-source candidates exist, but species-specific applicability, exact provision and effective version were not independently verified"
            elif counts.get("needs_review", 0) or counts.get("rejected", 0):
                if reason_counts.get("source_verification_not_verified", 0):
                    missing_type = "source_unverified_or_pending"
                elif reason_counts.get("source_span_provenance_incomplete", 0) or reason_counts.get("page_provenance_missing", 0):
                    missing_type = "provenance_incomplete"
                elif reason_counts.get("multiple_target_species_in_chunk_applicability_ambiguous", 0):
                    missing_type = "species_applicability_or_scope_requires_review"
                else:
                    missing_type = "candidate_not_yet_atomic_direct_and_category_verified"
                status_reason = "candidates exist, but none passed every Silver/verified readiness gate"
            else:
                missing_type = "insufficient_distinct_units"
                status_reason = "fewer than five distinct ready units"
            matrix.append({
                "species": species, "category": category, "target_count": 5,
                "screened_count": len(ids), "promoted_count": len(units),
                "silver_ready_count": silver, "verified_ready_count": verified,
                "needs_review_count": counts.get("needs_review", 0), "duplicate_count": counts.get("duplicate", 0),
                "rejected_count": counts.get("rejected", 0), "current_shortfall": max(0, 5-ready),
                "cell_status": "READY_5_PLUS" if ready >= 5 else ("PARTIAL_1_TO_4" if ready else "NO_EVIDENCE"),
                "screening_candidates_present": bool(ids),
                "source_search_performed": False, "structurally_infeasible": False,
                "gap_classification": missing_type, "gap_detail": status_reason,
            })
            best = []
            for cid in ids[:10]:
                if cid in candidate_by_id:
                    c = candidate_by_id[cid]
                    best.append({"candidate_id": cid, "source": c["source"], "status": c["candidate_processing_status"], "reasons": c["reasons"][:8]})
                else:
                    row = next((x for x in (high_candidates.get(cell, []) + calc_candidates.get(cell, [])) if str(x.get("chunk_id")) == cid), None)
                    if row:
                        best.append({"candidate_id": cid, "source_title": row.get("source_title"), "document_id": row.get("document_id"), "page": row.get("page_start"), "status": "needs_review", "reasons": ["candidate cue only; item-level verification required"]})
            if ready < 5:
                gap_registry.append({
                    "species": species, "category": category, "target_count": 5,
                    "ready_count": ready, "shortfall_count": 5-ready,
                    "missing_knowledge_type": missing_type,
                    "best_remaining_candidates": best,
                    "recommended_source_type": {
                        "Fact": "Fisheries Research Institute or peer-reviewed species-specific aquaculture reference",
                        "Water Quality": "official fisheries research / technical manual with explicit species-specific water parameter evidence",
                        "Disease": "Fisheries Research Institute or official diagnostic/manual source with species applicability",
                        "Climate / Cold": "government or research-institute source documenting species-specific temperature/cold response",
                        "Safe Medication / Law": "official competent authority regulation or current official approved-use source",
                        "Calculation": "official or recognized technical manual with formula, inputs, units, validity conditions and rounding rule",
                    }[category],
                    "required_verification": ["explicit exact support span", "complete document/page/checksum provenance", "species/category applicability", "atomic nonduplicate proposition", "current official applicability for high-risk rules" if category == "Safe Medication / Law" else "source verification and quality gate"],
                    "source_search_performed": False,
                    "structural_infeasibility_conclusion": "not_assessed_before_targeted_source_search",
                })

    # Candidate audit: all 486 screening rows remain traceable with their original IDs.
    status_counts = Counter(row["candidate_processing_status"] for row in candidates)
    mapped_candidate_count = sum(bool(x.get("species_category_assignment", {}).get("species") and x.get("species_category_assignment", {}).get("category")) for x in candidates)
    pool_unit_records: list[dict[str, Any]] = []
    write_jsonl(OUT / "evidence_units_v1.jsonl", evidence_units)
    write_json(OUT / "evidence_fact_duplicates.json", {
        "method": "exact normalized candidate text within species/category; numeric text preserved; no semantic near-duplicate auto-collapse",
        "exact_duplicate_groups": duplicate_groups + duplicate_unit_groups,
        "exact_duplicate_groups_count": len(duplicate_groups) + len(duplicate_unit_groups),
        "candidate_records_excluded_as_exact_duplicates": sum(x["duplicate_count_excluded"] for x in duplicate_groups + duplicate_unit_groups),
        "near_duplicate_review_policy": "not auto-merged; requires human/source comparison",
        "formula_duplicate_groups": formula_dupes,
        "formula_duplicate_groups_count": len(formula_dupes),
        "warning": "No candidate was counted as a ready Evidence Unit solely because it appeared in a chunk or matched a lexical cue.",
    })
    write_json(OUT / "screening_processing_report.json", {
        "inputs": {
            "normal_risk_screening_pool_rows": len(pool), "pool_sha256": pool_sha,
            "evaluation_corpus_rows": len(corpus), "retrieval_eligible_chunks": retrieval_count, "corpus_sha256": corpus_sha,
            "input_rows_have_unique_chunk_ids": len({x.get('chunk_id') for x in pool}) == len(pool),
            "all_pool_chunks_exist_and_text_checksums_match": all(not (set(make_pool_candidate(x, corpus_by_id)["reasons"]) & {"chunk_missing_from_evaluation_corpus", "content_checksum_does_not_match_text", "pool_text_differs_from_corpus_text"}) for x in pool),
        },
        "candidate_counts": {
            "normal_screening_chunks_processed": len(pool),
            "pool_rows_with_species_and_normal_category_metadata_all_statuses": mapped_candidate_count,
            "phase20_prior_screening_candidate_assignment_sum_under_its_narrower_rule": prior_scan_assignment_sum,
            "count_definitions_differ": True,
            "count_definition_note": "The pool mapping count includes accepted, review_candidate, and rejected rows; the prior 176 Phase 20 matrix count used a narrower screening rule and includes calculation/high-risk assignments. They are not additive or interchangeable.",
            "unassigned_or_non_target_species_category_pool_candidates": len(pool)-mapped_candidate_count,
            "calculation_candidate_species_assignments_processed": sum(len(x) for x in calc_candidates.values()),
            "calculation_candidate_unique_chunk_ids": len({r.get('chunk_id') for rows in calc_candidates.values() for r in rows}),
            "medication_law_candidate_species_assignments_processed": sum(len(x) for x in high_candidates.values()),
            "medication_law_candidate_unique_chunk_ids": len({r.get('chunk_id') for rows in high_candidates.values() for r in rows}),
            "pool_processing_status_counts": dict(status_counts),
        },
        "per_candidate": candidates,
        "reclassification": {"attempted": True, "rule": "requires explicit species string in candidate text and a single category-specific direct-support marker in the same literal clause; no LLM used", "reclassified_count": reclassified_count, "limitation": "metadata-only assignments were not expanded; ambiguous items remain needs_review"},
        "source_additions_this_run": 0,
    })

    write_json(OUT / "normal_risk_promotion.json", {
        "normal_categories": ["Fact", "Water Quality", "Disease", "Climate / Cold"],
        "candidate_rows_processed": len(pool), "mapped_candidate_rows": mapped_candidate_count,
        "silver_ready_units": len([u for u in evidence_units if u["risk_level"] == "normal" and u["readiness_status"] == "silver_ready"]),
        "promotion_rule": "exact direct support, source and span checks, species/category applicability, quality gate, and nonduplicate atomic proposition all required",
        "human_review_required_for_silver": False,
        "human_reviewed_units": 0,
        "promotion_status": "no_units_promoted" if not evidence_units else "units_promoted",
        "decision_note": "The evidence pool is an aid to screening, not proof of atomic facts. Candidate chunks with OCR/structure concerns, mixed species, pending verification, non-atomic spans or uncertain category support remain needs_review/rejected.",
        "units": evidence_units,
    })
    write_jsonl(OUT / "high_risk_units.jsonl", high_rows)
    by_species_high = []
    for species in SPECIES:
        rows = high_candidates.get((species, "Safe Medication / Law"), [])
        by_species_high.append({"species": species, "screened_count": len(rows), "verified_ready_count": 0, "needs_review_count": len(rows), "candidate_ids": [r.get("chunk_id") for r in rows], "status": "needs_review" if rows else "missing"})
    write_json(OUT / "high_risk_source_audit.json", {
        "official_only_rule": True, "source_additions_this_run": 0,
        "candidate_assignment_count": len(high_rows), "unique_candidate_chunk_count": len({r["candidate_id"] for r in high_rows}),
        "verified_ready_count": 0, "species_cells": by_species_high,
        "items": high_rows,
        "limitations": ["Corpus flags source as official/current, but this Step 2 did not perform current-law research or item-specific legal applicability review.", "No medication dose or withdrawal interval recommendations were generated."],
    })
    write_jsonl(OUT / "calculation_formula_registry_v1.jsonl", formula_registry)
    write_json(OUT / "calculation_validation.json", {
        "candidate_species_assignments_processed": len(formula_registry),
        "unique_candidate_chunks": len({r["chunk_id"] for r in formula_registry}),
        "literal_formula_candidates_extracted": sum(bool(r["formula"]) for r in formula_registry),
        "verified_ready_formula_units": 0,
        "deterministic_gold_answers_created": 0,
        "candidate_llm_or_judge_used_for_gold": False,
        "formula_duplicate_groups": len(formula_dupes),
        "status": "needs_review",
        "reason": "The candidate scan cue does not establish a complete formula unit; no unit met source verification, full variable/unit/range/assumption/rounding/tolerance requirements in this corpus-only pass.",
    })
    write_json(OUT / "existing_corpus_evidence_matrix.json", {
        "species": list(SPECIES), "categories": list(CATEGORIES), "cell_count": 36, "target_distinct_units_per_cell": 5,
        "candidate_counts_are_assignments_not_unique_facts": True,
        "cells": matrix,
        "summary": {
            "READY_5_PLUS": sum(r["cell_status"] == "READY_5_PLUS" for r in matrix),
            "PARTIAL_1_TO_4": sum(r["cell_status"] == "PARTIAL_1_TO_4" for r in matrix),
            "NO_EVIDENCE": sum(r["cell_status"] == "NO_EVIDENCE" for r in matrix),
            "cells_with_no_screening_candidate": sum(r["screened_count"] == 0 for r in matrix),
            "cells_with_candidates_but_no_ready_unit": sum(r["screened_count"] > 0 and r["silver_ready_count"] + r["verified_ready_count"] == 0 for r in matrix),
            "STRUCTURALLY_INFEASIBLE": 0,
            "silver_ready_units": sum(r["silver_ready_count"] for r in matrix),
            "verified_ready_units": sum(r["verified_ready_count"] for r in matrix),
            "needs_review_assignments": sum(r["needs_review_count"] for r in matrix),
            "duplicate_assignments": sum(r["duplicate_count"] for r in matrix),
            "rejected_assignments": sum(r["rejected_count"] for r in matrix),
        },
        "structural_feasibility_note": "Targeted source search has not occurred. No cell is called structurally infeasible in this report.",
    })
    write_json(OUT / "targeted_gap_registry.json", {
        "source_additions_this_run": 0, "source_search_performed": False,
        "gap_count": len(gap_registry), "cells": gap_registry,
        "priority_order": "Cells with no existing candidate first; then high-risk/calculation source verification gaps; then normal-risk cells with candidates requiring species/category/span review.",
    })
    matrix_summary = read_json(OUT / "existing_corpus_evidence_matrix.json")["summary"]
    normal_cells = [r for r in matrix if r["category"] in NORMAL_CATEGORIES.values()]
    high_cells = [r for r in matrix if r["category"] == "Safe Medication / Law"]
    calc_cells = [r for r in matrix if r["category"] == "Calculation"]
    r1_gates = r1.get("gates", {})
    phase20_2_ready = bool(
        r1_gates.get("four_models_ready") is True and r1_gates.get("independent_judge_ready") is True
        and all(r["silver_ready_count"] >= 5 for r in normal_cells)
        and all(r["verified_ready_count"] >= 5 for r in high_cells)
        and all(r["verified_ready_count"] >= 5 for r in calc_cells)
        and corpus_sha == expected_corpus
    )
    write_json(OUT / "readiness_after_step2.json", {
        "based_on": "actual Step 2 item-level candidate processing; no inferred zero-as-completion",
        "normal_evidence_ready": all(r["silver_ready_count"] >= 5 for r in normal_cells),
        "high_risk_ready": all(r["verified_ready_count"] >= 5 for r in high_cells),
        "calculation_ready": all(r["verified_ready_count"] >= 5 for r in calc_cells),
        "strict_matrix_ready": all(r["silver_ready_count"] + r["verified_ready_count"] >= 5 for r in matrix),
        "benchmark_design_amendment_required": False,
        "benchmark_design_amendment_status": "not_assessed; no structural infeasibility declared before targeted source search",
        "source_additions_this_run": 0,
        "final_corpus_ready": True,
        "final_corpus_identity": "Evaluation Corpus v2 (unchanged alias from Phase 20.1R)",
        "e4_final_ready": True,
        "e4_final_identity": "historical E4-compatible frozen baseline; not rebuilt",
        "phase20_2_benchmark_construction_ready": phase20_2_ready,
        "winner": None,
        "phase20_1R_identity_gates_preserved": {"four_models_ready": r1_gates.get("four_models_ready"), "independent_judge_ready": r1_gates.get("independent_judge_ready")},
        "reason": "Existing-corpus promotion found no qualifying ready units in this conservative item-level pass; normal/high-risk/calculation gates remain false.",
    })

    # Capture a read-only live Streamlit GET if an existing service is already listening; never start it.
    streamlit = {"check": "read_only_http_get_no_service_start", "url": "http://127.0.0.1:8501", "status": "not_checked", "http_status": None, "error": None}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8501", timeout=2) as response:
            streamlit.update({"status": "responded", "http_status": response.status})
    except urllib.error.HTTPError as exc:
        streamlit.update({"status": "responded", "http_status": exc.code})
    except Exception as exc:
        streamlit.update({"status": "unavailable_without_starting_service", "error": f"{type(exc).__name__}: {exc}"})
    historical_smoke = read_json(HISTORICAL_PRODUCTION_SMOKE) if HISTORICAL_PRODUCTION_SMOKE.is_file() else {}
    streamlit["historical_phase20_1_smoke"] = {
        "http_status": historical_smoke.get("streamlit_http_status"),
        "passed": historical_smoke.get("smoke_passed"),
        "captured_at": "Phase 20.1 historical compatibility report",
    }

    protected_after = frozen_phase15_20_snapshot()
    phase20_1_after = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in phase20_1_dir.rglob("*") if p.is_file()}
    db_after = {"size_bytes": DB_PATH.stat().st_size, "mtime_ns": DB_PATH.stat().st_mtime_ns, "sha256": sha256_file(DB_PATH)}
    step0_unchanged = sha256_file(STEP0) == step0_sha
    baseline_unchanged = sha256_file(R3_BASELINE) == baseline_sha
    frozen_diff = sorted(path for path in set(protected_before) | set(protected_after) if protected_before.get(path) != protected_after.get(path))
    phase20_1_diff = sorted(path for path in set(phase20_1_before) | set(phase20_1_after) if phase20_1_before.get(path) != phase20_1_after.get(path))
    compatibility = {
        "evaluation_corpus_v2_unchanged": sha256_file(CORPUS_PATH) == corpus_sha,
        "evidence_pool_unchanged": sha256_file(POOL_PATH) == pool_sha,
        "source_additions_this_run": 0,
        "indexes_or_e4_rebuilt": False,
        "phase15_20_protected_file_count_before": len(protected_before),
        "phase15_20_protected_files_unchanged": not frozen_diff,
        "phase15_20_changed_paths": frozen_diff,
        "phase20_1_protected_file_count_before": len(phase20_1_before),
        "phase20_1_protected_files_unchanged": not phase20_1_diff,
        "phase20_1_changed_paths": phase20_1_diff,
        "phase20_1R_and_step0_step1_reports_unchanged": step0_unchanged and baseline_unchanged,
        "step0_sha256_unchanged": step0_unchanged,
        "step1_sha256_unchanged": baseline_unchanged,
        "rag_store_sqlite3_before": db_before,
        "rag_store_sqlite3_after": db_after,
        "rag_store_sqlite3_unchanged": db_before == db_after,
        "production_streamlit": streamlit,
        "production_app_modified": False,
        "overall_frozen_compatibility_pass": not frozen_diff and not phase20_1_diff and db_before == db_after and step0_unchanged and baseline_unchanged,
    }
    write_json(OUT / "compatibility.json", compatibility)

    summary_counts = {
        "normal_screening_chunks_processed": len(pool), "mapped_pool_candidates_all_statuses": mapped_candidate_count,
        "phase20_prior_screening_candidate_assignment_sum": prior_scan_assignment_sum,
        "evidence_units_created": len(evidence_units), "exact_chunk_or_unit_duplicate_groups": len(duplicate_groups) + len(duplicate_unit_groups),
        "formula_duplicate_groups": len(formula_dupes),
        "formula_duplicate_candidate_exclusions": sum(x["duplicate_count_excluded"] for x in formula_dupes),
        "exact_duplicate_candidate_exclusions": sum(x["duplicate_count_excluded"] for x in duplicate_groups + duplicate_unit_groups),
        "normal_silver_ready": sum(r["silver_ready_count"] for r in matrix if r["category"] in NORMAL_CATEGORIES.values()),
        "high_risk_verified_ready": 0, "verified_calculation_formulas": 0,
        "calculation_candidate_assignments": len(formula_registry), "high_risk_candidate_assignments": len(high_rows),
        "matrix": matrix_summary,
    }
    write_json(OUT / "execution_manifest.json", {
        "phase": "RAG v2 Phase 20.1E", "execution_revision": "phase20_1E_exec_r3", "step": "Step 2 Existing-Corpus Evidence Unit Promotion",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "completed_existing_corpus_only",
        "baseline_reports": {"step0": "reports/evaluation/final_model_selection/phase20_1E_exec_r3/environment_preflight.json", "step1": "reports/evaluation/final_model_selection/phase20_1E_exec_r3/baseline_integrity.json"},
        "input_checksums": {"evidence_pool_v1_sha256": pool_sha, "evaluation_corpus_v2_sha256": corpus_sha},
        "counts": summary_counts, "source_additions_this_run": 0,
        "prohibitions_observed": {"formal_questions_created": False, "candidate_scoring_run": False, "selection_holdout_created": False, "winner_selected": False, "corpus_rebuilt": False, "e4_rebuilt": False, "production_migrated": False},
    })
    write_json(OUT / "tests.json", {"status": "not_run_yet", "note": "Updated after executing requested tests."})
    summary = [
        "# Phase 20.1E Exec r3 — Step 2 Summary", "",
        "Scope: existing Evaluation Corpus v2 only. No external sources, question generation, candidate scoring, index rebuild, E4 rebuild, or production changes.", "",
        f"- Screening chunks processed: {len(pool)}; pool rows with species/normal-category metadata (all statuses): {mapped_candidate_count}; prior Phase 20 narrower assignment sum: {prior_scan_assignment_sum} (different rule; not additive).",
        f"- Calculation candidate assignments: {len(formula_registry)} across {len({r['chunk_id'] for r in formula_registry})} unique chunks.",
        f"- Medication/Law candidate assignments: {len(high_rows)} across {len({r['candidate_id'] for r in high_rows})} unique chunks.",
        f"- Ready Evidence Units: {len(evidence_units)} (normal Silver {summary_counts['normal_silver_ready']}; high-risk verified {summary_counts['high_risk_verified_ready']}; calculation verified {summary_counts['verified_calculation_formulas']}).",
        f"- Exact duplicate groups: {len(duplicate_groups) + len(duplicate_unit_groups)}; formula duplicate groups: {len(formula_dupes)} ({summary_counts['formula_duplicate_candidate_exclusions']} repeated formula candidate instances flagged); exact fact/unit exclusions: {summary_counts['exact_duplicate_candidate_exclusions']}. Similarity-based duplicate claims were not made.",
        f"- Matrix: READY_5_PLUS={matrix_summary['READY_5_PLUS']}, PARTIAL_1_TO_4={matrix_summary['PARTIAL_1_TO_4']}, NO_EVIDENCE={matrix_summary['NO_EVIDENCE']} (zero ready units); zero candidate={matrix_summary['cells_with_no_screening_candidate']}, candidates but no ready unit={matrix_summary['cells_with_candidates_but_no_ready_unit']}; structurally infeasible=0 (not assessed before source search).",
        "- Source additions: 0. Evaluation Corpus v2 and historical E4 remain frozen; no index rebuilt.",
        f"- Readiness: normal={all(r['silver_ready_count'] >= 5 for r in normal_cells)}, high-risk={all(r['verified_ready_count'] >= 5 for r in high_cells)}, calculation={all(r['verified_ready_count'] >= 5 for r in calc_cells)}, Phase20.2={phase20_2_ready}.",
        f"- Frozen artifact / SQLite compatibility: {compatibility['overall_frozen_compatibility_pass']}; Streamlit live check={streamlit['status']} ({streamlit.get('http_status')}).",
        "",
        "Candidate rows are screening records, not human-validated facts or formal questions. No AI model was used to author claims or calculation gold answers.",
    ]
    (OUT / "step2_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return {"output_dir": str(OUT), "candidate_counts": summary_counts, "matrix": matrix, "readiness": read_json(OUT / "readiness_after_step2.json"), "compatibility": compatibility}


if __name__ == "__main__":
    try:
        result = build_step2()
        print(json.dumps({"status": "ok", "output_dir": result["output_dir"], "counts": result["candidate_counts"]}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        raise
