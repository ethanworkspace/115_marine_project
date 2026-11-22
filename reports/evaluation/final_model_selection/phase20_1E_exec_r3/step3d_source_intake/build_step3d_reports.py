from __future__ import annotations

import hashlib
import http.client
import json
import os
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

try:
    import pymupdf as fitz
    FITZ_AVAILABLE = True
except Exception as exc:
    fitz = None
    FITZ_AVAILABLE = False
    FITZ_ERROR = f"{type(exc).__name__}: {exc}"


ROOT = pathlib.Path.cwd()
S3C = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3c_evidence_expansion"
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3d_source_intake"
NOW = datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump_json(name, obj):
    path = OUT / name
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def dump_jsonl(name, rows):
    path = OUT / name
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def file_facts(rel):
    if not rel:
        return {"path": None, "exists": False, "size_bytes": None, "sha256": None, "format": None}
    p = pathlib.Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_file():
        return {"path": str(p), "exists": False, "size_bytes": None, "sha256": None, "format": p.suffix.lower() or None}
    st = p.stat()
    return {
        "path": str(p),
        "exists": True,
        "size_bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": sha_file(p),
        "format": p.suffix.lower() or None,
    }


def pdf_facts(path, page_numbers=()):
    facts = file_facts(path)
    if not facts["exists"] or facts["format"] != ".pdf":
        return facts | {"pdf_open": False, "page_count": None, "metadata": None, "page_excerpts": [], "open_error": None}
    if not FITZ_AVAILABLE:
        return facts | {"pdf_open": False, "page_count": None, "metadata": None, "page_excerpts": [], "open_error": FITZ_ERROR}
    try:
        doc = fitz.open(facts["path"])
        excerpts = []
        for n in page_numbers:
            if 1 <= n <= doc.page_count:
                text = doc[n - 1].get_text("text")
                excerpts.append({"page_pdf_1based": n, "text_prefix": text[:1600]})
        result = facts | {
            "pdf_open": True,
            "page_count": doc.page_count,
            "metadata": doc.metadata,
            "page_excerpts": excerpts,
            "open_error": None,
        }
        doc.close()
        return result
    except Exception as exc:
        return facts | {"pdf_open": False, "page_count": None, "metadata": None, "page_excerpts": [], "open_error": f"{type(exc).__name__}: {exc}"}


if not OUT.is_dir():
    OUT.mkdir(parents=True)
if any(p.name != "build_step3d_reports.py" for p in OUT.iterdir()):
    raise SystemExit(f"Refusing to overwrite non-empty execution directory: {OUT}")

# Reconfirm Step3C baselines before creating the requested reports.
ready = read_json(S3C / "readiness_after_step3c.json")
matrix_doc = read_json(S3C / "evidence_matrix_after_step3c.json")
packet = read_jsonl(S3C / "official_source_acquisition_packet.jsonl")
compat3c = read_json(S3C / "compatibility.json")
context_doc = read_json(S3C / "context_only_eligibility_audit.json")
decisions = read_jsonl(S3C / "normal_risk_batch_decisions.jsonl")
law3c = read_json(S3C / "medication_law_remaining_gaps.json")
calc3c = read_json(S3C / "calculation_remaining_gaps.json")
test_probe = read_json(S3C / "test_tempfile_probe.json")
interpreters = read_json(S3C / "test_interpreter_inventory.json")

matrix_cells = matrix_doc.get("cells", [])
checks = {
    "normal_silver_ready_11": ready.get("normal_risk_ready_units") == 11,
    "normal_shortfall_109": ready.get("normal_risk_shortfall") == 109,
    "medication_law_0_of_30": ready.get("medication_law_verified_ready_units") == 0 and ready.get("medication_law_target_units") == 30,
    "calculation_0_of_30": ready.get("calculation_verified_ready_units") == 0 and ready.get("calculation_target_units") == 30,
    "matrix_1_ready_5_partial_30_empty": (
        ready.get("strict_matrix_cells_at_target") == 1
        and ready.get("strict_matrix_cells_partial") == 5
        and ready.get("strict_matrix_cells_empty") == 30
        and len(matrix_cells) == 36
    ),
    "nine_registered_sources": len(packet) == 9,
    "zero_formal_admissions": ready.get("formal_admissions") == 0,
    "benchmark_not_ready": ready.get("phase20_2_benchmark_construction_ready") is False,
    "winner_null": ready.get("winner") is None,
}
if not all(checks.values()):
    dump_json("baseline_check.json", {"checked_at_utc": NOW, "checks": checks, "step3c_readiness": ready, "source_rows": len(packet), "matrix_cells": len(matrix_cells), "status": "baseline_mismatch_stop"})
    raise SystemExit("Step3C baseline did not match the user-specified values; no Step3D analysis performed.")

# Local source inspection is read-only. Existing files are not copied into staging.
source_notes = {
    "MOA-LAW-FL035443": {
        "pages": [1],
        "decision": "awaiting_user_document",
        "reason": "A 14-page local Attachment I exists and opens, but its 2019-era bytes are not matched to the official consolidated revision recorded as 2025-01-08. Current complete annex and item-level effective/species/use scope remain unverified.",
        "admission_review_candidate": False,
    },
    "FA-HAZARD": {
        "pages": [],
        "decision": "awaiting_user_document",
        "reason": "No local original file is registered; the exact official attachment/PDF and dated source content are required.",
        "admission_review_candidate": False,
    },
    "FA-COLD": {
        "pages": [1],
        "decision": "ready_for_admission_review",
        "reason": "An existing one-page official-site print snapshot opens and identifies Fisheries Agency, title, URL and 2026-07-02 timestamp. It was not acquired in this execution. Bind it to the currently served version and resolve reuse terms before admission.",
        "admission_review_candidate": True,
    },
    "TFRIN-MILKFISH-COLD": {
        "pages": [],
        "decision": "awaiting_user_document",
        "reason": "No local original or reproducible HTML snapshot/checksum exists for the official TFRI Q&A.",
        "admission_review_candidate": False,
    },
    "TFRIN-GROUPER-DISEASE": {
        "pages": [],
        "decision": "awaiting_user_document",
        "reason": "The source-specific TFRI page/attachment has no local original. Manual 17 is a distinct existing source and does not substitute for this source record.",
        "admission_review_candidate": False,
    },
    "TFRIN-MANUAL17": {
        "pages": [2, 91, 124],
        "decision": "ready_for_admission_review",
        "reason": "The existing 218-page official 2023 Technical Manual No.17 PDF opens; title, issuing institute and edition are visible, and recorded pages are locatable. Reuse permission and official page-to-file version linkage remain unresolved.",
        "admission_review_candidate": True,
    },
    "TFRIN-TILAPIA-ARTICLE": {
        "pages": [1, 2],
        "decision": "needs_provenance_review",
        "reason": "The existing 7-page article opens and shows journal/TFRI imprint; local bytes are checksummed. Official catalogue-to-file binding and reuse conditions are not verified; experimental strain results cannot be generalized.",
        "admission_review_candidate": False,
    },
    "TFRIN-SGR-FCR": {
        "pages": [],
        "decision": "awaiting_user_document",
        "reason": "No local original exists. The identified silver-croaker fry study also requires an explicit applicability review before any transfer to the six target species.",
        "admission_review_candidate": False,
    },
    "TFRIN-FCR-EXPLAIN": {
        "pages": [],
        "decision": "awaiting_user_document",
        "reason": "No local original or fixed HTML snapshot exists; the general definition alone is insufficient for a fully specified deterministic formula unit.",
        "admission_review_candidate": False,
    },
}

intake_rows = []
verify_rows = []
manual_rows = []
newly_acquired = 0
for src in packet:
    sid = src["source_id"]
    facts = pdf_facts(src.get("existing_local_candidate"), source_notes[sid]["pages"])
    expected = src.get("existing_candidate_sha256")
    hash_match = (facts.get("sha256") == expected) if expected and facts.get("exists") else None
    intake_rows.append({
        "source_id": sid,
        "priority": src.get("priority"),
        "official_title": src.get("official_title"),
        "issuing_authority": src.get("issuing_authority"),
        "official_landing_url": src.get("official_landing_url"),
        "exact_document_url": src.get("exact_document_url"),
        "required_version_or_effective_date": src.get("required_version_or_effective_date"),
        "existing_local_candidate": facts,
        "expected_local_sha256": expected,
        "local_sha256_matches_step3c": hash_match,
        "newly_acquired_this_execution": False,
        "copied_to_staging": False,
        "decision": source_notes[sid]["decision"],
        "blocker": source_notes[sid]["reason"],
    })
    pdf_page_numbers = [row["page_pdf_1based"] for row in source_notes[sid]["pages"]] if False else []
    inspected = facts.get("page_excerpts", [])
    verification = {
        "source_id": sid,
        "source_title": src.get("official_title"),
        "issuing_authority": src.get("issuing_authority"),
        "official_url": src.get("official_landing_url"),
        "exact_document_url": src.get("exact_document_url"),
        "document_available": facts.get("exists", False),
        "original_file_path": facts.get("path"),
        "file_format": facts.get("format"),
        "file_size_bytes": facts.get("size_bytes"),
        "document_sha256": facts.get("sha256"),
        "expected_candidate_sha256": expected,
        "checksum_match_to_step3c_candidate": hash_match,
        "document_opened": facts.get("pdf_open") if facts.get("format") == ".pdf" else (facts.get("exists", False) if facts.get("format") == ".html" else False),
        "page_count": facts.get("page_count"),
        "official_identity_verified": sid in {"FA-COLD", "TFRIN-MANUAL17"} and hash_match is True,
        "publication_revision_effective_dates": src.get("required_version_or_effective_date"),
        "current_version_verified_this_execution": False,
        "relevant_pages_or_sections": [e["page_pdf_1based"] for e in inspected],
        "page_text_inspected": bool(inspected),
        "support_span_rechecked_this_execution": False,
        "source_to_local_bytes_binding": "existing candidate/hash only; no current official server comparison performed",
        "species_scope": src.get("target_species_and_categories", {}).get("species", []),
        "topic_scope": src.get("target_species_and_categories", {}).get("categories", []),
        "rights_or_reuse": src.get("rights_or_usage_restrictions"),
        "parser_or_table_quality": "not fully re-audited in Step3D; prior Step3B/3C page extraction evidence retained",
        "review_decision": source_notes[sid]["decision"],
        "blocking_reason": source_notes[sid]["reason"],
        "newly_downloaded": False,
    }
    if facts.get("format") == ".pdf" and not facts.get("pdf_open"):
        verification["blocking_reason"] += " PDF open failed: " + str(facts.get("open_error"))
        verification["review_decision"] = "needs_original_document"
    verify_rows.append(verification)
    if not facts.get("exists") or sid == "MOA-LAW-FL035443":
        manual_rows.append({
            "source_id": sid,
            "official_title": src.get("official_title"),
            "official_url": src.get("official_landing_url"),
            "expected_document_type": src.get("expected_document_type"),
            "required_original_file": "Current official original PDF or reproducible dated HTML snapshot with exact attachment URL and version/effective date.",
            "target_species": src.get("target_species_and_categories", {}).get("species", []),
            "target_categories": src.get("target_species_and_categories", {}).get("categories", []),
            "download_blocker": src.get("download_blocker"),
            "manual_verification_needed": source_notes[sid]["reason"],
            "handoff_status": "awaiting_user_document",
            "existing_file_is_new_download": False,
        })
    elif sid == "TFRIN-TILAPIA-ARTICLE":
        manual_rows.append({
            "source_id": sid,
            "official_title": src.get("official_title"),
            "official_url": src.get("official_landing_url"),
            "expected_document_type": "official catalogue record or direct official file binding for the existing local PDF",
            "required_original_file": "No duplicate PDF requested; provide official catalogue/file linkage and reuse terms for the existing checksum.",
            "target_species": src.get("target_species_and_categories", {}).get("species", []),
            "target_categories": src.get("target_species_and_categories", {}).get("categories", []),
            "download_blocker": src.get("download_blocker"),
            "manual_verification_needed": source_notes[sid]["reason"],
            "handoff_status": "awaiting_user_document",
            "existing_file_is_new_download": False,
        })

# Context-only and warning rows are audited separately; their frozen labels remain untouched.
ctx_rows = context_doc.get("rows", [])
context_only_ids = {
    "targeted_ff8f499834b104e5",
    "targeted_7400f262ec2de577",
    "targeted_b6635396f8904ce3",
    "targeted_644cdc14755d80c6",
    "targeted_583c210ee8e8ddfd",
}
contexts = [r for r in ctx_rows if r.get("candidate_id") in context_only_ids]
warning_ids = {
    "chunk_d3fa6bb110cf5c619aaf34078dcc9809",
    "chunk_9e01efee566c5dbba22615ccd9fc54a7",
    "chunk_936cc1cd031454fa9ab5d754225ad180",
    "chunk_70f1227b5c4f53ff85e347c63e4988a5",
    "chunk_3c1310048516502595a2f6053f63a93b",
}
warnings = [r for r in decisions if r.get("candidate_id") in warning_ids]

context_reason = {
    "targeted_ff8f499834b104e5": "Frozen retrieval_role=context_only and benchmark_eligible=false; source identity is pending. Existing page/span/hash evidence does not override frozen eligibility; resolve authority/version and rights in a separately versioned corpus.",
    "targeted_7400f262ec2de577": "Frozen context_only label remains. Local one-page Fisheries Agency print snapshot is dated 2026-07-02; link it to currently served version and confirm reuse terms before future corpus review.",
    "targeted_b6635396f8904ce3": "Frozen context_only label remains. Experimental tilapia strain paper only supports its observed study conditions; it cannot support a species-general overwintering rule.",
    "targeted_644cdc14755d80c6": "Frozen context_only label remains. Manual 17 official identity and page support are recorded, but reproduction/digitization/reprint permission and proposition-level splitting remain unresolved.",
    "targeted_583c210ee8e8ddfd": "Frozen context_only label remains. Manual 17 official identity and page support are recorded, but reuse permission and proposition-level support review remain unresolved.",
}
eligibility_rows = []
future_rows = []
for row in contexts:
    record = {
        "candidate_id": row.get("candidate_id"),
        "kind": "context_only",
        "species": row.get("species"),
        "category": row.get("category"),
        "claim_candidate": row.get("claim_candidate"),
        "document_id": row.get("document_id"),
        "chunk_id": row.get("chunk_id"),
        "source_document": row.get("source_document"),
        "original_exclusion_reason": row.get("original_exclusion_reason"),
        "frozen_corpus_status": row.get("corpus_status"),
        "pdf_open_step3c": row.get("pdf_open"),
        "pdf_sha256": row.get("pdf_sha256"),
        "support_span_checks_step3c": row.get("support_span_checks", []),
        "source_authenticity": row.get("source_authenticity"),
        "rights_or_reuse": row.get("rights_or_reuse"),
        "blocker": context_reason.get(row.get("candidate_id"), row.get("step3b_blocking_reason")),
        "frozen_label_modified": False,
        "counted_as_silver": False,
        "next_action": "new corpus version review; preserve existing E4 and corpus",
    }
    eligibility_rows.append(record)
    if row.get("future_corpus_admission_candidate") is True:
        future_rows.append({
            "candidate_id": row.get("candidate_id"),
            "source_kind": "existing context_only source candidate",
            "species": row.get("species"),
            "category": row.get("category"),
            "document_id": row.get("document_id"),
            "chunk_id": row.get("chunk_id"),
            "required_remediation": row.get("required_remediation", []),
            "admission_status": "not_admitted",
            "corpus_version_required": "new explicit Evaluation Corpus version if approved",
        })
for row in warnings:
    reason = row.get("decision_reason")
    if row["candidate_id"] in {"chunk_d3fa6bb110cf5c619aaf34078dcc9809", "chunk_9e01efee566c5dbba22615ccd9fc54a7"}:
        reason = "Strict source identity gate remains false (source_verified=false, accepted_with_warning); paper is an experimental tilapia strain study and cannot be generalized beyond its study conditions."
    else:
        reason = "Strict source identity gate remains false (source_verified=false, accepted_with_warning); local original hash/page is corroborated but catalog/version/rights linkage remains unresolved. This is historical disease material, not current clinical advice."
    record = {
        "candidate_id": row.get("candidate_id"),
        "kind": "source_warning",
        "species": row.get("species"),
        "category": row.get("category"),
        "document_id": row.get("document_id"),
        "chunk_id": row.get("chunk_id"),
        "source_pdf_path": row.get("source_pdf_path"),
        "page": row.get("page_pdf_1based"),
        "source_pdf_sha256": row.get("source_pdf_sha256_actual"),
        "frozen_source_verified": row.get("frozen_source_verified"),
        "frozen_ingestion_status": row.get("frozen_ingestion_status"),
        "frozen_corpus_eligibility": {"retrieval_role": row.get("frozen_retrieval_role"), "benchmark_eligible": row.get("frozen_benchmark_eligible")},
        "decision": row.get("decision"),
        "blocker": reason,
        "frozen_label_modified": False,
        "counted_as_silver": False,
    }
    eligibility_rows.append(record)
    future_rows.append({
        "candidate_id": row.get("candidate_id"),
        "source_kind": "source_verified=false / accepted_with_warning",
        "species": row.get("species"),
        "category": row.get("category"),
        "document_id": row.get("document_id"),
        "chunk_id": row.get("chunk_id"),
        "required_remediation": ["bind the exact local bytes to an official catalog/source record", "review reuse/rights", "re-evaluate proposition scope and freshness"],
        "admission_status": "not_admitted",
        "corpus_version_required": "new explicit Evaluation Corpus version if approved",
    })

# Build summaries of the outstanding legal and calculation gates from the frozen Step3C records.
law_gaps = {
    "baseline_verified_ready": law3c.get("baseline_verified_ready"),
    "verified_ready_this_execution": 0,
    "target": law3c.get("target"),
    "current_official_parent_source": law3c.get("current_official_parent_source"),
    "local_attachment": law3c.get("local_attachment"),
    "attachment_bytes_match_current_online_version": False,
    "species_specific_authorization_verified": False,
    "species_gaps": law3c.get("remaining_species_gaps", []),
    "required_next_evidence": [
        "current complete official Attachment I bytes or reproducible official snapshot and exact file URL",
        "effective/revision date plus item/provision identity",
        "specific species, indication/use and any product authorization scope",
        "official source checksum and exact page/section/span",
        "review separating general aquaculture legal rules from item-level authorization",
    ],
    "prohibited_inference": "No dosage, withdrawal period, product approval or species authorization inferred.",
    "admission_or_readiness_changed": False,
}
calc_gaps = {
    "candidate_assignment_rows": calc3c.get("candidate_assignment_rows"),
    "unique_candidate_chunks": calc3c.get("unique_candidate_chunks"),
    "nonempty_formula_cue_rows": calc3c.get("nonempty_formula_cue_rows"),
    "distinct_text_cues": calc3c.get("distinct_text_cues"),
    "verified_formula_count": calc3c.get("verified_formula_count"),
    "target": calc3c.get("target"),
    "formula_cues": calc3c.get("formula_cues"),
    "blocking_gaps": calc3c.get("blocking_gaps"),
    "deterministic_reference_implementation_created": False,
    "gold_questions_created": 0,
    "llm_used_for_gold": False,
    "verification_changed": False,
}

# Recheck Step3C's 11 frozen checksum anchors and SQLite metadata/hash, opening SQLite read-only.
anchor_results = []
for item in compat3c.get("current_frozen_anchor_rechecks", []):
    p = ROOT / item["path"]
    actual = sha_file(p) if p.is_file() else None
    st = p.stat() if p.is_file() else None
    anchor_results.append({
        "name": item.get("name"),
        "path": item.get("path"),
        "expected_sha256": item.get("expected_sha256"),
        "actual_sha256": actual,
        "sha256_match": actual == item.get("expected_sha256"),
        "expected_size_bytes": item.get("size_bytes"),
        "actual_size_bytes": st.st_size if st else None,
        "expected_mtime_ns": item.get("mtime_ns"),
        "actual_mtime_ns": st.st_mtime_ns if st else None,
    })
sqlite_path = ROOT / "rag_store.sqlite3"
sqlite_integrity = {"read_only": True, "path": str(sqlite_path), "quick_check": "not_run", "error": None}
try:
    conn = sqlite3.connect(sqlite_path.as_uri() + "?mode=ro", uri=True, timeout=5)
    sqlite_integrity["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.close()
except Exception as exc:
    sqlite_integrity["error"] = f"{type(exc).__name__}: {exc}"

ollama = {"checked": False, "method": "read-only localhost HTTP GET", "expected_from_step3c": compat3c.get("ollama_tags_GET_read_only_this_run", {}).get("digests", {}), "actual_digests": None, "matches": None, "error": None}
try:
    conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=2)
    conn.request("GET", "/api/tags")
    response = conn.getresponse()
    body = response.read()
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")
    tags = json.loads(body.decode("utf-8"))
    actual_tags = {m.get("name"): m.get("digest") for m in tags.get("models", [])}
    expected_tags = ollama["expected_from_step3c"]
    ollama.update({"checked": True, "http_status": response.status, "actual_digests": actual_tags, "matches": all(actual_tags.get(k) == v for k, v in expected_tags.items())})
    conn.close()
except Exception as exc:
    ollama["error"] = f"{type(exc).__name__}: {exc}"
    ollama["matches"] = None

sqlite_stat = sqlite_path.stat()
compatibility = {
    "checked_at_utc": NOW,
    "write_scope": str(OUT.relative_to(ROOT)),
    "formal_source_admissions": 0,
    "formal_corpus_rebuilds": 0,
    "formal_e4_rebuilds": 0,
    "benchmark_questions_created": 0,
    "formal_model_scoring": 0,
    "winner": None,
    "frozen_anchor_checks": anchor_results,
    "all_11_anchor_hashes_match": len(anchor_results) == 11 and all(x["sha256_match"] for x in anchor_results),
    "sqlite": {
        "path": "rag_store.sqlite3",
        "size_bytes": sqlite_stat.st_size,
        "mtime_ns": sqlite_stat.st_mtime_ns,
        "sha256": sha_file(sqlite_path),
        "expected_sha256": next((x["expected_sha256"] for x in compat3c.get("current_frozen_anchor_rechecks", []) if x.get("name") == "rag_store_sqlite3"), None),
        "readonly_quick_check": sqlite_integrity,
    },
    "ollama_frozen_model_digests": ollama,
    "phase15_20_protected_files": {
        "previous_comprehensive_check": compat3c.get("phase15_20_protected_files"),
        "current_step": "Only read-only checks of 11 anchored files and Ollama tags were performed; no comprehensive rehash of all historical protected files in this step.",
    },
    "phase20_1_protected_reports": {
        "previous_comprehensive_check": compat3c.get("phase20_1_protected_reports"),
        "current_step": "Historical reports were read-only; all new writes are isolated in Step3D output directory.",
    },
    "production_http_smoke": "not_tested",
    "production_app_modified": False,
    "corpus_modified": False,
    "indexes_modified": False,
    "model_artifacts_modified": False,
}

test_plan = {
    "prior_suite": test_probe.get("prior_full_suite"),
    "full_suite_rerun_this_step": "not_run",
    "current_execution_reproduction": "not_run; no validated repair or newly approved cleanable temp root",
    "root_cause_assessment": {
        "most_supported_category": "managed Sandbox/temp filesystem access or cleanup boundary",
        "evidence": [
            "TemporaryDirectory creation succeeded in the Step3C probe but file write raised PermissionError errno 13.",
            "Cleanup of the isolated temporary directory and pytest explicit basetemp raised WinError 5.",
            "Sandbox cleanup was denied; no ACL/security change was authorized or attempted.",
        ],
        "not_proven": ["specific NTFS ACL defect", "Defender/WDAC block", "test-code regression"],
    },
    "interpreter_dependency_difference": interpreters.get("interpreters"),
    "single_interpreter_has_pytest_docx_and_pymupdf": interpreters.get("single_interpreter_has_all_three"),
    "required_safe_prerequisites": [
        "Sandbox-approved temp root where the chosen interpreter can create, write, read and delete a file/directory and pytest basetemp without WinError 5.",
        "One approved disposable interpreter/environment containing pytest, python-docx and PyMuPDF at project-compatible versions; no installation performed in this step.",
        "Pass minimal tempfile and pytest tmp_path round-trip/cleanup probes before rerunning unchanged tests.",
    ],
    "regression_gate": "pending; rerun the unchanged failed tests and collection cases after prerequisites pass; preserve all tracebacks and do not skip/relax assertions.",
    "security_policy_or_acl_changed": False,
    "dependencies_changed": False,
}

matrix_new = []
for cell in matrix_cells:
    matrix_new.append({
        "species": cell.get("species"),
        "category": cell.get("category"),
        "baseline_ready": cell.get("total_formal_ready", cell.get("baseline_ready", 0)),
        "new_existing_corpus_silver_ready_step3d": 0,
        "new_external_staged_candidates": 0,
        "external_admitted_ready": 0,
        "total_formal_ready": cell.get("total_formal_ready", 0),
        "remaining_shortfall": cell.get("remaining_shortfall"),
        "source_review_status": cell.get("source_review_status"),
        "source_gap_classification": cell.get("source_gap_classification"),
        "readiness_unchanged": True,
    })

admission = {
    "checked_at_utc": NOW,
    "pending_official_source_records": len(packet),
    "newly_acquired_and_verified_official_originals": newly_acquired,
    "existing_local_documents_rechecked": sum(1 for x in intake_rows if x["existing_local_candidate"]["exists"]),
    "ready_for_admission_review": [x["source_id"] for x in intake_rows if x["decision"] == "ready_for_admission_review"],
    "needs_provenance_review": [x["source_id"] for x in intake_rows if x["decision"] == "needs_provenance_review"],
    "awaiting_user_document": [x["source_id"] for x in intake_rows if x["decision"] == "awaiting_user_document"],
    "formal_admission_allowed_this_step": False,
    "formal_admissions": 0,
    "blockers": [
        "Current official MOA Attachment I file/version is not matched to the existing local PDF.",
        "FA-COLD and Manual17 require version/reuse-rights resolution before any corpus decision.",
        "TFRIN tilapia article needs official catalogue-to-file provenance binding.",
        "Six source items lack a usable current original or exact official file evidence; one existing article needs an official binding record.",
        "No official originals were newly downloaded or copied to staging in this execution.",
    ],
    "go_no_go": "NO-GO for formal Source Admission; two existing documents can enter admission review with listed blockers, one needs provenance review, six await user originals/current versions.",
}

# Write all required deliverables with exclusive creation; no prior report is overwritten.
dump_jsonl("source_intake_manifest.jsonl", intake_rows)
dump_jsonl("official_document_verification.jsonl", verify_rows)
dump_jsonl("manual_acquisition_pending.jsonl", manual_rows)
dump_json("eligibility_resolution_audit.json", {
    "checked_at_utc": NOW,
    "context_only_candidate_count": len(contexts),
    "source_warning_candidate_count": len(warnings),
    "records": eligibility_rows,
    "frozen_corpus_eligibility_modified": False,
    "silver_ready_increment": 0,
    "final_benchmark_ready_count_changed": False,
})
dump_jsonl("future_corpus_admission_queue.jsonl", future_rows)
dump_json("medication_law_verification_gaps.json", law_gaps)
dump_json("calculation_verification_gaps.json", calc_gaps)
dump_json("test_environment_blocker_plan.json", test_plan)
dump_json("admission_readiness.json", admission)
dump_json("compatibility.json", compatibility)

summary = [
    "# Phase 20.1E Exec r3 — Step 3D Summary",
    "",
    f"- Step3C baseline checks: {sum(checks.values())}/{len(checks)} PASS; 11 Silver units, 1/36 target cells, 5 partial, 30 zero, high-risk 0/30, calculation 0/30.",
    f"- Official-source records reviewed: {len(packet)}. Existing local source candidates checked: {admission['existing_local_documents_rechecked']}. New originals acquired or staged: {newly_acquired}.",
    "- Source decisions: " + ", ".join(f"{k}={len([x for x in intake_rows if x['decision']==k])}" for k in sorted({x['decision'] for x in intake_rows})),
    "- Ready for Admission Review only: " + (", ".join(admission["ready_for_admission_review"]) or "none") + ". No formal admission occurred.",
    "- Requires provenance review: " + (", ".join(admission["needs_provenance_review"]) or "none") + ".",
    "- Awaiting user originals/current versions: " + (", ".join(admission["awaiting_user_document"]) or "none") + ".",
    "- FA-COLD and Manual17 are existing local documents, not newly acquired. FA-COLD's local page snapshot is dated 2026-07-02; Manual17 is the identified official 2023 manual, but reuse permission/version linkage remains open.",
    "- The local MOA annex opens and has a SHA-256, but it is not byte-matched to the current consolidated revision and cannot verify item-level authorizations.",
    "- Five context-only rows and five explicitly designated source-warning rows were audited. Their frozen eligibility labels were not changed and none was counted as new Silver.",
    "- Medication/Law remains 0/30; current complete Attachment I plus specific item/species/use review is needed. Calculation remains 0/30; formula conditions and source applicability are incomplete. No Gold questions or deterministic answer implementation were made.",
    "- Test suite was not rerun. Step3C evidence still shows tempfile write errno 13 and cleanup/pytest basetemp WinError 5; no interpreter has pytest, python-docx and PyMuPDF together. Safe regression gate remains pending.",
    f"- Frozen anchors: {sum(1 for x in anchor_results if x['sha256_match'])}/{len(anchor_results)} SHA-256 matches; SQLite quick_check={sqlite_integrity['quick_check']}; Ollama digest check={'matched' if ollama['matches'] is True else 'not verified' if ollama['matches'] is None else 'mismatch'}.",
    "- Production HTTP smoke: not_tested. Corpus/index/model artifacts were not modified.",
    "- Formal admissions=0; corpus rebuilds=0; E4 rebuilds=0; benchmark questions=0; model scoring=0; Winner=null.",
    "",
    "## Recommendation",
    "",
    "NO-GO for formal admission or benchmark construction. Provide the current official MOA Attachment I, Fisheries Agency hazard analysis, TFRI milkfish cold page/file, TFRI grouper-disease attachment, and the formula source originals through an approved handoff. Also provide the official catalogue/file binding for the existing tilapia article. Resolve the Manual17 reuse permission and FA-COLD version linkage before admission review can advance.",
]
(OUT / "step3d_summary.md").open("x", encoding="utf-8", newline="\n").write("\n".join(summary) + "\n")

print(json.dumps({
    "status": "completed_source_intake_review",
    "baseline_checks": checks,
    "source_rows": len(packet),
    "existing_local_candidates": admission["existing_local_documents_rechecked"],
    "new_originals_acquired": newly_acquired,
    "ready_for_admission_review": admission["ready_for_admission_review"],
    "awaiting_user_document": admission["awaiting_user_document"],
    "anchor_matches": sum(1 for x in anchor_results if x["sha256_match"]),
    "anchor_count": len(anchor_results),
    "sqlite_quick_check": sqlite_integrity["quick_check"],
    "ollama_digest_match": ollama["matches"],
    "output": str(OUT),
}, ensure_ascii=False, indent=2))
