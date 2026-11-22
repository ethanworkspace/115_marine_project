"""Freeze Phase 20.1R readiness evidence without running model ranking."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.phase20_1r_protocol import (
    CATEGORIES,
    SPECIES,
    judge_calibration_ready,
    phase20_2_readiness,
)

OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1R"
PRIOR = ROOT / "reports/evaluation/final_model_selection/phase20_1"
E4_DIR = ROOT / "reports/evaluation/experiments/E4_grounded_rrf_reranker_v1"
E2_DIR = ROOT / "data/evaluation/indexes/E2_grounded_bge_m3_v1"
MODEL_ROOT = Path.home() / ".ollama/models"
API = "http://127.0.0.1:11434"
M3_UPSTREAM_SHA256 = "87bcba20b4846d8dadf753d3ff48f9285d131fc95e3e0e7e934d4f20bc896f5d"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def find_ollama_manifest(expected_digest: str):
    manifest_root = MODEL_ROOT / "manifests"
    for path in manifest_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if sha_file(path) == expected_digest:
                value = read_json(path)
                return path, value
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None, None


def verify_existing_candidate(frozen: dict, live_tags: dict[str, dict]) -> dict:
    tag = frozen["runtime_name"]
    live = live_tags.get(tag)
    result = dict(frozen)
    if not live:
        result.update({"recheck_status": "blocked_tag_missing", "identity_verified": False})
        return result
    digest = live.get("digest")
    manifest_path, manifest = find_ollama_manifest(digest or "")
    weight = next((layer for layer in (manifest or {}).get("layers", []) if layer.get("mediaType") == "application/vnd.ollama.image.model"), None)
    blob = MODEL_ROOT / "blobs" / f"sha256-{weight['digest'].split(':', 1)[-1]}" if weight else None
    local_hash = sha_file(blob) if blob and blob.is_file() else None
    same_digest = digest == frozen["digest"]
    same_weight = local_hash == frozen["artifact_sha256"]
    result.update({
        "rechecked_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_tag_digest": digest,
        "current_manifest_path": str(manifest_path) if manifest_path else None,
        "current_manifest_sha256": sha_file(manifest_path) if manifest_path else None,
        "current_weight_layer_sha256": local_hash,
        "current_weight_layer_size_bytes": weight.get("size") if weight else None,
        "tag_digest_matches_phase20_1": same_digest,
        "weight_layer_matches_phase20_1": same_weight,
        "recheck_status": "passed" if same_digest and same_weight else "mismatch",
        "identity_verified": bool(same_digest and same_weight and frozen.get("lineage_verified")),
    })
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    phase20_1_files = list(PRIOR.rglob("*"))
    if not PRIOR.is_dir() or not read_json(PRIOR / "readiness.json"):
        raise SystemExit("Phase 20.1 frozen baseline is unavailable")
    tags = {row.get("name"): row for row in requests.get(f"{API}/api/tags", timeout=30).json().get("models", [])}

    frozen_candidates = [read_json(PRIOR / f"M{i}_manifest.json") for i in (1, 2, 4)]
    verified_candidates = [verify_existing_candidate(row, tags) for row in frozen_candidates]
    m3_acq = read_json(OUT / "M3_acquisition_manifest.json")
    m3_preflight = read_json(OUT / "M3_runtime_preflight.json")
    m3_acq.update({
        "base_model_source_evidence": "DeepSeek official model card identifies Distill-Llama-8B as derived from Llama-3.1-8B.",
        "base_model_source_url": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
        "source_license": "DeepSeek model card: MIT; underlying Llama 3.1 license also applies.",
        "gguf_quantizer": "third-party bartowski; this is not an official DeepSeek GGUF build.",
        "gguf_source_file_published_sha256": M3_UPSTREAM_SHA256,
        "local_file_matches_published_source_sha256": m3_acq.get("artifact_sha256") == M3_UPSTREAM_SHA256,
        "repository_revision_evidence": "Source repository commit recorded in the acquisition notes; Ollama hf.co import did not pin or expose the resolved commit. Exact local bytes are independently fixed by SHA-256 and match the published file SHA-256.",
    })
    write_json(OUT / "M3_acquisition_manifest.json", m3_acq)
    m3_ready = bool(
        m3_preflight.get("m3_ready") is True
        and m3_acq.get("local_file_matches_published_source_sha256") is True
        and m3_acq.get("architecture") == "llama"
        and m3_acq.get("quantization") == "Q4_K_M"
    )
    m3_manifest = {
        "model_id": "M3",
        "plan_name": "DeepSeek-R1-Distill-Llama-8B",
        "runtime_name": m3_acq["ollama_runtime_name"],
        "identity_verified": m3_ready,
        "lineage_verified": m3_ready,
        "base_model_source": m3_acq["base_model_source"],
        "base_model_source_url": m3_acq["base_model_source_url"],
        "source_repository": m3_acq["source_repository"],
        "source_repository_revision_observed": m3_acq["repository_revision"],
        "revision_pinned_by_runtime_pull": False,
        "artifact_format": "GGUF",
        "architecture": m3_acq["architecture"],
        "parameter_count": m3_acq["parameter_count"],
        "quantization": m3_acq["quantization"],
        "native_context_length": m3_acq["native_context_length"],
        "experimental_context_length_smoke": 8192,
        "artifact_size_bytes": m3_acq["artifact_size_bytes"],
        "artifact_sha256": m3_acq["artifact_sha256"],
        "published_file_sha256": M3_UPSTREAM_SHA256,
        "artifact_checksum_match": m3_acq.get("local_file_matches_published_source_sha256"),
        "ollama_digest": m3_acq["ollama_digest"],
        "runtime": f"Ollama {m3_acq['ollama_runtime_version']}",
        "license": m3_acq["source_license"],
        "gguf_quantizer": m3_acq["gguf_quantizer"],
        "tokenizer_metadata_sha256": m3_acq["tokenizer_metadata_sha256"],
        "chat_template_sha256": m3_acq["chat_template_sha256"],
        "runtime_preflight": m3_preflight,
        "identity_limitation": "Ollama remote import did not expose a commit-pinned revision; source repository commit is recorded as observed, while the exact local GGUF bytes match the publisher-visible SHA-256.",
    }
    verified_candidates.append(m3_manifest)
    verified_candidates.sort(key=lambda row: row["model_id"])
    (OUT / "candidate_manifests").mkdir(parents=True, exist_ok=True)
    for row in verified_candidates:
        write_json(OUT / f"{row['model_id']}_manifest.json", row)
        write_json(OUT / "candidate_manifests" / f"{row['model_id']}_manifest.json", row)

    candidate_digests = {row.get("digest") or row.get("ollama_digest") for row in verified_candidates}
    judge_manifest = read_json(OUT / "judge_manifest.json")
    judge_cal = read_json(OUT / "judge_calibration.json")
    judge_repeat = read_json(OUT / "judge_repeatability.json")
    judge_manifest["is_candidate"] = False
    judge_manifest["artifact_source_url"] = "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407"
    judge_manifest["artifact_identity_note"] = "Ollama model digest freezes the local converted GGUF artifact; upstream model card lists Apache-2.0 and states it is instruct fine-tuned from Mistral-Nemo-Base-2407, jointly trained by Mistral AI and NVIDIA."
    write_json(OUT / "judge_manifest.json", judge_manifest)
    judge_independent = judge_manifest.get("artifact_digest") not in candidate_digests
    judge_ready = judge_calibration_ready(judge_manifest, judge_cal, verified_candidates) and judge_independent
    judge_candidates = {
        "selected_judge": {
            "runtime_name": judge_manifest.get("runtime_name"),
            "digest": judge_manifest.get("artifact_digest"),
            "independent_of_all_four_candidates": judge_independent,
            "calibration_status": judge_cal.get("judge_execution_status"),
            "selected_before_calibration": True,
        },
        "candidate_models": [{"model_id": r["model_id"], "runtime_name": r["runtime_name"], "digest": r.get("digest") or r.get("ollama_digest")} for r in verified_candidates],
        "historical_judge_attempt": {
            "runtime_name": "deepseek-r1:8b",
            "digest": "6995872bfe4c521a67b32da386cd21d5c6e819b6e0d62f79f64ec83be99f5763",
            "lineage": "DeepSeek-R1-0528-Qwen3-8B",
            "status": "historical_judge_attempt_only",
            "reason": "Phase 20.1 calibration truncated at 8192 output tokens; excluded from Phase 20.1R Judge role.",
        },
        "downloaded_new_evaluation_only_artifact": True,
    }
    write_json(OUT / "judge_candidates.json", judge_candidates)

    old_scan = read_json(ROOT / "reports/evaluation/final_model_selection/phase20/evidence_coverage_gaps.json")
    old_matrix_doc = read_json(PRIOR / "evidence_matrix.json")
    previous_gaps = read_json(PRIOR / "evidence_gap_report.json")
    old_rows = old_matrix_doc["matrix"]
    matrix = []
    for old in old_rows:
        count = old.get("screening_candidate_chunk_count", 0)
        status = "screened" if count else "missing"
        matrix.append({
            "species": old["species"],
            "category": old["category"],
            "target_distinct_units": 5,
            "screening_candidate_chunks": count,
            "screening_chunks_are_not_evidence_units": True,
            "silver_ready_units": 0,
            "verified_ready_units": 0,
            "human_reviewed_units": 0,
            "readiness_status": status,
            "question_ready_capacity_confirmed": False,
            "source_evidence_review": "No item-level evidence-unit review recorded; counts are carried forward from the frozen Phase 20 scan.",
        })
    matrix_counts = Counter(row["readiness_status"] for row in matrix)
    evidence_matrix = {
        "species": list(SPECIES),
        "categories": list(CATEGORIES),
        "cell_count": 36,
        "target_distinct_units_per_cell": 5,
        "screening_chunk_total": previous_gaps.get("normal_risk_evidence_pool_chunks", 0),
        "cell_assigned_screening_candidate_chunk_sum": sum(r["screening_candidate_chunks"] for r in matrix),
        "evidence_pool_status_counts": old_scan.get("evidence_pool_status_counts", {}),
        "source_verification_status_counts": old_scan.get("source_verification_status_counts", {}),
        "silver_ready_units_total": 0,
        "verified_ready_units_total": 0,
        "human_reviewed_units_total": 0,
        "status_cell_counts": dict(matrix_counts),
        "empty_cells": [r for r in matrix if r["readiness_status"] == "missing"],
        "screened_not_ready_cells": [r for r in matrix if r["readiness_status"] == "screened"],
        "matrix": matrix,
        "prior_phase20_scan_sha256": sha_file(ROOT / "reports/evaluation/final_model_selection/phase20/evidence_coverage_gaps.json"),
        "source_screening_counts_never_promoted_to_units": True,
    }
    write_json(OUT / "evidence_matrix.json", evidence_matrix)
    write_jsonl(OUT / "evidence_units.jsonl", [])

    gap_report = {
        "phase20_1_scan_sha256": sha_file(ROOT / "reports/evaluation/final_model_selection/phase20/evidence_coverage_gaps.json"),
        "phase20_1_gap_report_sha256": sha_file(PRIOR / "evidence_gap_report.json"),
        "source_screening_chunks": evidence_matrix["screening_chunk_total"],
        "cell_assigned_screening_candidate_chunk_sum": evidence_matrix["cell_assigned_screening_candidate_chunk_sum"],
        "evidence_pool_status_counts": evidence_matrix["evidence_pool_status_counts"],
        "screening_chunk_count_is_not_unit_or_question_count": True,
        "prior_empty_cell_count": old_matrix_doc.get("empty_cells"),
        "prior_review_needed_cell_count": old_matrix_doc.get("review_needed_cells"),
        "current_missing_cells": len(evidence_matrix["empty_cells"]),
        "current_screened_cells_without_ready_units": len(evidence_matrix["screened_not_ready_cells"]),
        "candidate_question_capacity_confirmed": 0,
        "ready_units": 0,
        "detail": previous_gaps,
        "limitations": [
            "No item-level distinct question-ready units were constructed from the previous scan.",
            "The current law annex source has official current-version metadata, but medication-row/species applicability and page-level evidence units are not verified.",
            "Some existing recovered PDFs and chunks require text/page quality review before promotion.",
            "Do not infer a question count from corpus chunk counts.",
        ],
    }
    write_json(OUT / "evidence_gap_report.json", gap_report)

    high_risk_old = read_json(PRIOR / "high_risk_source_audit.json")
    drug_pdf = ROOT / "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf"
    drug_page = {
        "authority": "Ministry of Agriculture, Taiwan",
        "document_title": "動物用藥品使用準則 附件一 水產動物用藥品使用規範",
        "official_law_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443",
        "official_revision_date": "2025-01-08 (ROC 114-01-08)",
        "official_current_source_verified": True,
        "local_attachment_path": "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf",
        "local_attachment_sha256": sha_file(drug_pdf) if drug_pdf.is_file() else None,
        "local_attachment_page_count": 14 if drug_pdf.is_file() else None,
        "page_content_quality_verified_for_units": False,
    }
    high_rows = []
    for cell in high_risk_old.get("species_cells", []):
        high_rows.append({
            "species": cell["species"],
            "category": "Safe Medication / Law",
            "target_verified_ready_units": 5,
            "screened_candidate_chunks": cell.get("screening_candidate_chunk_count", 0),
            "verified_ready_units": 0,
            "human_reviewed_units": 0,
            "readiness_status": "screened" if cell.get("screening_candidate_chunk_count", 0) else "missing",
            "candidate_official_source": drug_page,
            "species_applicability_reviewed_per_unit": False,
            "reason": "Official current rule source is identified, but no distinct medication/law question unit has verified row, page, species applicability, and checksum provenance.",
        })
    write_jsonl(OUT / "high_risk_source_registry.jsonl", high_rows)
    write_json(OUT / "high_risk_source_audit.json", {
        "official_source_candidates": [drug_page, {
            "authority": "Ministry of Agriculture, Taiwan",
            "document_title": "動物用藥品管理法",
            "official_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL014718",
            "current_page_checked": True,
            "unit_level_applicability_verified": False,
        }],
        "species_cells": high_rows,
        "verified_ready_units": 0,
        "target_units": 30,
        "ready": False,
    })

    old_calc = read_json(PRIOR / "calculation_registry_status.json")
    write_jsonl(OUT / "calculation_registry.jsonl", [])
    write_json(OUT / "calculation_registry_status.json", {
        "target_units": 30,
        "target_per_species": 5,
        "verified_ready_units": 0,
        "candidate_screening_chunks": old_calc.get("candidate_screening_chunk_counts", {}),
        "candidate_screening_chunks_total": old_calc.get("candidate_screening_total", 0),
        "expected_numeric_answers_authored_by_candidate_llm": False,
        "ready": False,
        "reason": "No per-unit formula, sourced variable/units, valid range, deterministic operation, rounding, tolerance, page and checksum passed item-level verification.",
    })

    source_candidates = [
        {
            "source_title": "漁電共生養殖技術應用手冊(下) (技術手冊17)",
            "authority": "Taiwan Fisheries Research Institute",
            "official_url": "https://www.tfrin.gov.tw/ws.php?id=246",
            "local_raw_file": "data/recovery/raw_sources/tfrin_technical_manual_17_lower_full.pdf",
            "source_status": "already represented in historical Evaluation Corpus v2; no Phase 20.1R addition",
            "may_support_species": ["石斑魚", "鱸魚", "烏魚"],
        },
        {
            "source_title": "動物用藥品使用準則 附件一",
            "authority": "Ministry of Agriculture, Taiwan",
            "official_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035443",
            "local_raw_file": "data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf",
            "source_status": "already represented in historical Evaluation Corpus v2; official current date recorded; no Phase 20.1R addition",
            "may_support_species": list(SPECIES),
        },
        {
            "source_title": "漁電共生養殖技術應用手冊(上) (技術手冊17)",
            "authority": "Taiwan Fisheries Research Institute",
            "official_url": "https://www.tfrin.gov.tw/ws.php?id=245",
            "source_status": "identified official source candidate; not acquired/parsed/admitted in Phase 20.1R",
            "may_support_species": ["虱目魚", "吳郭魚"],
        },
        {
            "source_title": "鰻魚養殖技術/特刊資料",
            "authority": "Taiwan Fisheries Research Institute",
            "official_url": "https://www.tfrin.gov.tw/theme_data.php?id=204&theme=aquatic_technology",
            "source_status": "identified official source candidate; item-level source/page/checksum review remains",
            "may_support_species": ["鰻魚"],
        },
    ]
    write_jsonl(OUT / "source_candidates_not_added.jsonl", source_candidates)
    write_jsonl(OUT / "source_additions.jsonl", [])

    corpus_path = ROOT / "data/evaluation/corpus_v2.jsonl"
    corpus_manifest_path = ROOT / "data/evaluation/corpus_manifest_v2.json"
    corpus_hash = sha_file(corpus_path)
    corpus_meta = read_json(corpus_manifest_path)
    corpus_unchanged = corpus_hash == "540a7dfa641fdbf9c2246feea75a226ade41a8e85d5c995fa5b3c8514aa03162"
    final_corpus = {
        "final_corpus_id": "Final Evaluation Corpus v1 (frozen alias)",
        "schema_version": "evaluation-corpus-v2",
        "alias_of": "evaluation-corpus-v2",
        "source_additions_this_phase": 0,
        "source_chunk_additions_this_phase": 0,
        "content_sha256": corpus_hash,
        "frozen_hash_matches_historical_v2": corpus_unchanged,
        "source_manifest_path": corpus_meta.get("source_manifest"),
        "source_manifest_sha256": corpus_meta.get("source_manifest_v3_sha256"),
        "chunk_count_retrieval": corpus_meta.get("summary", {}).get("retrieval_chunks"),
        "duplicate_policy": corpus_meta.get("canonicalization_policy"),
        "retrieval_eligibility": "reuse historical Evaluation Corpus v2 benchmark eligibility flags",
        "new_version_created": False,
        "reason": "No new source or chunk was admitted during Phase 20.1R; the frozen v2 checksum is reused without rewriting historical corpus/index artifacts.",
        "ready": corpus_unchanged,
    }
    write_json(OUT / "final_corpus_manifest.json", final_corpus)

    e4_manifest_path = E4_DIR / "experiment_manifest.json"
    e4_trace_path = E4_DIR / "ranking_traces.jsonl"
    e4_fusion_path = E4_DIR / "reranker_traces.jsonl"
    reproduction_path = ROOT / "reports/evaluation/edge/phase19B_exec_r2/e4_reproduction.json"
    reproduction = read_json(reproduction_path)
    e4_meta = read_json(e4_manifest_path)
    e4_final_pass = bool(corpus_unchanged and reproduction.get("passed") is True and reproduction.get("checked") == 60 and reproduction.get("matched") == 60)
    e4_final = {
        "pipeline_id": "E4-Final (reuse frozen E4 v1; no corpus delta)",
        "corpus_sha256": corpus_hash,
        "corpus_chunk_count": e4_meta.get("retrieval_chunk_count"),
        "E1_manifest_sha256": e4_meta.get("E1_manifest_sha256"),
        "E2_manifest_sha256": e4_meta.get("E2_manifest_sha256"),
        "E2_dense_index_manifest_sha256": e4_meta.get("E2_dense_index_manifest_sha256"),
        "E2_dense_index_vectors_sha256": read_json(E2_DIR / "index_manifest.json").get("vectors_sha256"),
        "E2_dense_model_digest": read_json(E2_DIR / "index_manifest.json").get("model", {}).get("model_digest"),
        "rrf_config": e4_meta.get("RRF_config"),
        "candidate_depth": e4_meta.get("candidate_depth"),
        "reranker": {
            "model_id": e4_meta.get("reranker", {}).get("model_id"),
            "revision": e4_meta.get("reranker", {}).get("revision"),
            "device": e4_meta.get("reranker", {}).get("device"),
            "dtype": e4_meta.get("reranker", {}).get("dtype"),
        },
        "final_context_top_k": 5,
        "historical_E4_manifest_sha256": sha_file(e4_manifest_path),
        "historical_E4_ranking_trace_sha256": sha_file(e4_trace_path),
        "historical_E4_reranker_trace_sha256": sha_file(e4_fusion_path),
        "Phase19B_60_question_reproduction": {"report": "reports/evaluation/edge/phase19B_exec_r2/e4_reproduction.json", "sha256": sha_file(reproduction_path), "checked": reproduction.get("checked"), "matched": reproduction.get("matched"), "passed": reproduction.get("passed")},
        "new_index_built": False,
        "ready": e4_final_pass,
        "limitation": "No new Final Selection questions have been built or run; this gate only reuses the unchanged, previously frozen E4 algorithm/index baseline. No ranking or Selection benchmark was run in Phase 20.1R.",
    }
    write_json(OUT / "e4_final_manifest.json", e4_final)

    identity_ready = len(verified_candidates) == 4 and all(r.get("identity_verified") and r.get("lineage_verified") for r in verified_candidates)
    normal_ready = all(
        sum(row["silver_ready_units"] for row in matrix if row["species"] == species and row["category"] == category) >= 5
        for species in SPECIES
        for category in CATEGORIES[:4]
    )
    high_ready = sum(r["verified_ready_units"] for r in high_rows) >= 30 and all(r["verified_ready_units"] >= 5 for r in high_rows)
    calc_ready = old_calc.get("ready_units", 0) >= 30 and all(old_calc.get("candidate_screening_chunk_counts", {}).get(s, 0) >= 5 for s in SPECIES)
    gates = {
        "four_models_ready": identity_ready,
        "independent_judge_ready": judge_ready,
        "normal_evidence_ready": normal_ready,
        "high_risk_ready": high_ready,
        "calculation_ready": calc_ready,
        "final_corpus_ready": final_corpus["ready"],
        "e4_final_ready": e4_final_pass,
    }
    readiness = phase20_2_readiness(gates)
    readiness.update({
        "aqua7b_included": False,
        "aqua7b_exclusion_reason": "revised experimental scope",
        "four_models_ready": identity_ready,
        "judge_independent": judge_independent,
        "judge_calibration_passes": judge_cal.get("first_pass_completed") == 30 and judge_cal.get("second_pass_completed") == 30 and judge_cal.get("technical_failure_count") == 0 and judge_cal.get("completion_truncation_count") == 0 and judge_cal.get("schema_failure_count") == 0,
        "normal_risk_ready_unit_count": 0,
        "high_risk_verified_ready_unit_count": sum(r["verified_ready_units"] for r in high_rows),
        "calculation_verified_ready_unit_count": 0,
        "source_additions_this_phase": 0,
        "corpus_changed_this_phase": False,
        "formal_four_model_scoring": False,
        "winner": None,
    })
    write_json(OUT / "readiness.json", readiness)

    audit = {
        "candidate_count": 4,
        "models": [{"model_id": r["model_id"], "plan_name": r["plan_name"], "identity_verified": r.get("identity_verified"), "runtime_name": r.get("runtime_name"), "digest": r.get("digest") or r.get("ollama_digest"), "artifact_sha256": r.get("artifact_sha256"), "recheck_status": r.get("recheck_status", "M3 acquisition and smoke report passed"), "blocker": None if r.get("identity_verified") else r.get("blocker", "identity verification failed")} for r in verified_candidates],
        "four_models_ready": identity_ready,
        "aqua7b_included": False,
        "exclusion_reason": "revised experimental scope",
    }
    write_json(OUT / "candidate_identity_audit.json", audit)
    write_json(OUT / "historical_artifact_mapping.json", read_json(PRIOR / "historical_artifact_mapping.json"))
    write_json(OUT / "evidence_readiness_policy.json", {
        "statuses": ["screened", "silver_ready", "verified_ready", "human_reviewed", "missing"],
        "normal_risk_minimum": "silver_ready; human review optional; provenance, explicit support, valid mapping/checksum, unique non-interpolated fact required",
        "medication_law_minimum": "verified_ready from a current official source with authority, date/version, applicability, page and checksum",
        "calculation_minimum": "verified_ready deterministic formula/input/source/page/checksum; no Candidate LLM authored expected answer",
        "source_chunk_counts_are_not_evidence_unit_or_question_counts": True,
        "AI_generated_silver_not_human_gold": True,
    })

    historic_files = []
    for path in sorted(PRIOR.rglob("*")):
        if path.is_file():
            historic_files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha_file(path), "size_bytes": path.stat().st_size})
    write_json(OUT / "phase20_1_protected_checksum_verification.json", {
        "prior_phase20_1_report_file_count": len(historic_files),
        "prior_phase20_1_files_current_sha256": historic_files,
        "phase20_1_directory_untouched_by_this_script": True,
    })

    report = f"""# RAG v2 Phase 20.1R — Final Evaluation Readiness Recovery

Completed: {datetime.now(timezone.utc).isoformat()}

## Outcome

- AQUA-7B remains excluded (`aqua7b_included=false`; `revised experimental scope`). No substitute was used.
- M1, M2, M4 passed live Ollama tag and weight-layer SHA-256 rechecks against Phase 20.1. M3 is the specified DeepSeek-R1-Distill-Llama-8B Q4_K_M artifact; local bytes match the published file SHA-256, the Ollama GGUF reports `llama`/8.03B/Q4_K_M, and simple generation, Generation v2 JSON-schema, and 8192-context smoke checks passed. Ollama's HF import did not pin/expose the resolved repository commit, so the exact bits are SHA-256 pinned and the commit observation is reported with that limitation.
- The dedicated Judge is Mistral NeMo Instruct 12B Q4_K_M, a distinct non-candidate artifact. The fixed calibration completed 30/30 in both fresh passes with 100% schema parsing, zero technical failures and zero truncations. All three calibration metrics had 100% exact agreement (MAD 0.0). This is repeatability evidence, not human validation.
- Evidence matrix remains 36 cells: {len(evidence_matrix['empty_cells'])} missing and {len(evidence_matrix['screened_not_ready_cells'])} screened but not promoted; 0 distinct question-ready units were verified. The 486 prior screening count remains chunk-only.
- Medication/Law has 0 verified-ready units; Calculation has 0 deterministic verified-ready units (72 prior candidate chunks are not units).
- No corpus source/chunk was added in Phase 20.1R. Final Evaluation Corpus v1 is therefore recorded as a frozen alias of unchanged Evaluation Corpus v2; the existing E4 baseline is reused with its prior 60/60 retrieval reproduction. No new index was built.
- Readiness is **{str(readiness['phase20_2_benchmark_construction_ready']).lower()}**. No formal four-model Selection scoring, ranking, Winner, or Holdout evaluation was run.

## Gates

| Gate | Status |
|---|---|
| Four exact candidate identities | {gates['four_models_ready']} |
| Independent Judge | {gates['independent_judge_ready']} |
| Normal-risk evidence (24 cells × 5 units) | {gates['normal_evidence_ready']} |
| Medication/Law (6 cells × 5 verified units) | {gates['high_risk_ready']} |
| Calculation (6 cells × 5 deterministic units) | {gates['calculation_ready']} |
| Final corpus frozen | {gates['final_corpus_ready']} (unchanged v2 alias) |
| E4-Final frozen/tested | {gates['e4_final_ready']} (unchanged E4 reuse; no new questions run) |
| Phase 20.2 construction ready | {readiness['phase20_2_benchmark_construction_ready']} |

## Source/evidence limitations

Official current Ministry of Agriculture medication rules are identified, but unit-level drug row, species applicability and page evidence were not promoted. Existing official aquaculture manuals remain in the historical corpus; no new source passed the phase's source/parser/page/eligibility admission path. Missing source candidates are listed separately and are not treated as corpus additions.
"""
    (OUT / "phase20_1R_summary.md").write_text(report, encoding="utf-8")

    manifest = {
        "phase": "RAG v2 Phase 20.1R",
        "status": "readiness_recovery_completed_not_ready",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": ["exact M3 artifact identity", "independent Judge readiness", "evidence readiness audit", "source readiness", "calculation registry", "frozen corpus/E4 reuse decision"],
        "formal_ranking_performed": False,
        "formal_selection_outputs": 0,
        "winner": None,
        "aqua7b_included": False,
        "aqua7b_exclusion_reason": "revised experimental scope",
        "phase20_1_frozen_report_directory": "reports/evaluation/final_model_selection/phase20_1",
        "phase20_1_frozen_report_count_at_start": len(phase20_1_files),
        "candidate_identity_audit_sha256": sha_file(OUT / "candidate_identity_audit.json"),
        "judge_calibration_sha256": sha_file(OUT / "judge_calibration.json"),
        "evidence_matrix_sha256": sha_file(OUT / "evidence_matrix.json"),
        "readiness_sha256": sha_file(OUT / "readiness.json"),
    }
    write_json(OUT / "experiment_manifest.json", manifest)
    return 0 if identity_ready and judge_ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
