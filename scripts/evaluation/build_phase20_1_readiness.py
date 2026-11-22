"""Build Phase 20.1 readiness artifacts from frozen local evidence.

This script never installs/downloads models, changes the corpus, or writes to
the original Phase 20 report directory.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.phase20_1_protocol import (
    SPECIES,
    CATEGORIES,
    empty_evidence_matrix,
    phase20_2_readiness,
)


PHASE20 = ROOT / "reports/evaluation/final_model_selection/phase20"
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1"
GAP_PATH = PHASE20 / "evidence_coverage_gaps.json"
IDENTITY_PATH = PHASE20 / "candidate_model_manifest.json"
JUDGE_PATH = PHASE20 / "judge_manifest.json"
POOL_PATH = ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"
DB_PATH = ROOT / "rag_store.sqlite3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_inventory(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rows.append({"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    return rows


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_identity_rows(source_manifest: dict) -> tuple[list[dict], dict]:
    source = {row["model_id"]: row for row in source_manifest["models"]}
    common = {
        "audit_timestamp_utc": timestamp(),
        "runtime": "Ollama 0.35.0",
        "artifact_format": "GGUF",
        "source_revisions": "Upstream pages identify model lineage; Ollama manifest digest freezes the local converted artifact.",
    }
    m1 = {
        **common, "model_id": "M1", "plan_name": "DeepSeek-R1-Distill-Qwen-7B",
        "runtime_name": "deepseek-r1:7b", "identity_verified": True,
        "lineage_verified": True, "architecture": "qwen2", "base_model": "DeepSeek-R1-Distill-Qwen",
        "parameter_count": 7615616512, "quantization": "Q4_K_M", "context_length": 131072,
        "artifact_size_bytes": 4683075440, "weight_layer_size_bytes": 4683073184,
        "digest": "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f",
        "artifact_sha256": "96c415656d377afbff962f6cdb2394ab092ccbcbaab4b82525bc4ca800fe8a49",
        "artifact_checksum_match": True, "tokenizer_identity": "Ollama GGUF tokenizer metadata sha256: 88f44ff31308607eb03a75af376cbe3a18c580e2fc54872e63b84e9fbd50d25b; tokenizer.ggml.model=gpt2; bos=151646; eos=151643",
        "source_url": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "source_license": "Upstream model license was not independently re-fetched in this audit; retained prior Phase 20 identity provenance.",
        "source_metadata": source["M1"]["source_metadata"],
        "ollama_manifest_sha256": source["M1"]["ollama_manifest_sha256"],
        "identity_evidence": ["prior Phase 20 identity passed", "local Ollama /api/show metadata", "local GGUF model layer SHA-256 recomputed and matched manifest"],
    }
    m2 = {
        **common, "model_id": "M2", "plan_name": "Qwen 2.5-Coder-7B-Instruct",
        "runtime_name": "qwen2.5-coder:7b", "identity_verified": True,
        "lineage_verified": True, "architecture": "qwen2", "base_model": "Qwen2.5 Coder 7B Instruct",
        "parameter_count": 7615616512, "quantization": "Q4_K_M", "context_length": 32768,
        "artifact_size_bytes": 4683087561, "weight_layer_size_bytes": 4683074048,
        "digest": "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364",
        "artifact_sha256": "60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463",
        "artifact_checksum_match": True, "tokenizer_identity": "Ollama GGUF tokenizer metadata sha256: 56e11a9607bb06a1d4366aad99d7da08353492440cc75bcffdd89a70ee6cb19c; tokenizer.ggml.model=gpt2; bos=151643; eos=151645",
        "source_url": "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct",
        "source_license": "Apache-2.0 (upstream metadata recorded in prior Phase 20 manifest)",
        "source_metadata": source["M2"]["source_metadata"],
        "ollama_manifest_sha256": source["M2"]["ollama_manifest_sha256"],
        "identity_evidence": ["prior Phase 20 identity passed", "local Ollama /api/show metadata explicitly identifies Instruct", "local GGUF model layer SHA-256 recomputed and matched manifest"],
    }
    m3 = {
        **common, "model_id": "M3", "plan_name": "DeepSeek-R1-Distill-Llama-8B",
        "runtime_name": None, "identity_verified": False, "lineage_verified": False,
        "candidate_M3": False, "candidate_artifact_status": "blocked_network_not_acquired",
        "architecture": "llama", "base_model": "Llama-3.1-8B",
        "parameter_count": 8030261248, "parameter_count_source": "upstream model card; no converted local GGUF to inspect",
        "quantization": "Q4 GGUF required; actual quantization unverified",
        "artifact_size_bytes": None, "weight_layer_size_bytes": None, "digest": None,
        "artifact_sha256": None, "artifact_checksum_match": False, "context_length": None,
        "tokenizer_identity": None,
        "source_url": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
        "source_revision": None, "source_license": "MIT plus upstream Llama license (as stated on official model card)",
        "traceable_quantized_source_candidate": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF/tree/935d400c2ed1a29cc2a1045df25ec7998fb4dfe4",
        "quantized_source_revision_status": "candidate source/revision reported by repository listing; not downloaded or independently verified locally",
        "network_failure": "Direct Hugging Face API access returned Windows WinError 10013; no network workaround attempted.",
        "identity_evidence": ["official DeepSeek model card confirms Distill-Llama-8B lineage and Llama-3.1-8B base", "no exact GGUF artifact, tokenizer, metadata, digest, or local runtime identity acquired"],
    }
    m4 = {
        **common, "model_id": "M4", "plan_name": "Gemma 2 (9B-It)",
        "runtime_name": "gemma2:9b", "identity_verified": True, "lineage_verified": True,
        "architecture": "gemma2", "base_model": "google/gemma-2-9b-it",
        "parameter_count": 9241705984, "quantization": "Q4_0", "context_length": 8192,
        "artifact_size_bytes": 5443152417, "weight_layer_size_bytes": 5443143296,
        "digest": "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b",
        "artifact_sha256": "ff1d1fc78170d787ee1201778e2dd65ea211654ca5fb7d69b5a2e7b123a50373",
        "artifact_checksum_match": True, "tokenizer_identity": "Ollama GGUF tokenizer metadata sha256: 4f2b4f18feba09dbe70b6869afe4f30b7b3a8656903e0ca7d6681966b0370540; tokenizer.ggml.model=llama; bos=2; eos=1",
        "source_url": "https://huggingface.co/google/gemma-2-9b-it",
        "official_runtime_tag_url": "https://ollama.com/library/gemma2/tags",
        "official_runtime_tag": "gemma2:9b-instruct-q4_0",
        "official_tag_digest_prefix": "ff02c3702f32",
        "source_license": "Gemma Terms of Use",
        "source_metadata": source["M4"]["source_metadata"],
        "ollama_manifest_sha256": source["M4"]["ollama_manifest_sha256"],
        "identity_evidence": ["Google official model card identifies Gemma 2 9B IT", "Ollama official instruct Q4_0 tag digest prefix matches local full manifest digest", "official tag lists 5.4 GB and 8K context consistent with local manifest", "local GGUF architecture/parameter count/Q4_0 and layer SHA-256 rechecked"],
        "source_revision": "Google model card does not expose an upstream commit revision in this audit; frozen local identity is the full Ollama manifest digest and model-layer checksum.",
    }
    return [m1, m2, m3, m4], {
        "old_deepseek_r1_8b": {
            "runtime_name": "deepseek-r1:8b",
            "digest": source["M3"]["digest"],
            "architecture": "qwen3",
            "basename": "DeepSeek-R1-0528-Qwen3",
            "parameter_count": 8190735360,
            "quantization": "Q4_K_M",
            "historical_artifact_only": True,
            "candidate_M3": False,
            "permitted_as_substitute": False,
            "reason": "local Ollama metadata identifies a Qwen3-based DeepSeek-R1-0528 artifact; required M3 is DeepSeek-R1-Distill-Llama-8B",
        }
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    generated_at = timestamp()
    prior_gap = read_json(GAP_PATH)
    old_judge = read_json(JUDGE_PATH)
    old_identity = read_json(IDENTITY_PATH)
    phase17_outputs_path = ROOT / "reports/evaluation/generation_models/phase17/per_question_metrics.jsonl"
    old_rows = {(row["species"], row["category"]): row for row in prior_gap["matrix"]}
    scan_rows = list(old_rows.values())
    phase20_before = file_inventory(PHASE20)
    db_before = {"path": "rag_store.sqlite3", "size_bytes": DB_PATH.stat().st_size, "mtime_ns": DB_PATH.stat().st_mtime_ns, "sha256": sha256(DB_PATH)}
    identities, historical = build_identity_rows(old_identity)

    write_json(OUT / "experiment_manifest.json", {
        "phase": "RAG v2 Phase 20.1 Final Evaluation Readiness Recovery",
        "created_at_utc": generated_at,
        "purpose": ["candidate artifact identity", "independent Judge readiness", "evidence readiness matrix", "calculation evidence registry", "high-risk source verification"],
        "formal_candidate_ranking": False,
        "winner_selection": False,
        "candidate_outputs_run": 0,
        "aqua7b_included": False,
    })
    write_json(OUT / "scope_change.json", {
        "original_proposal_model_count": 5,
        "actual_comparison_model_count": 4,
        "aqua7b_included": False,
        "exclusion_reason": "revised experimental scope",
        "aqua7b_downloaded": False,
        "aqua7b_deployed": False,
        "aqua7b_tested": False,
        "aqua7b_ranked": False,
        "proxy_model_created": False,
        "five_model_comparison_completed": False,
    })
    write_json(OUT / "candidate_identity_audit.json", {
        "four_models_ready": all(row["identity_verified"] for row in identities),
        "identity_rows_ready": sum(bool(row["identity_verified"]) for row in identities),
        "candidate_count": 4,
        "models": [{"model_id": row["model_id"], "plan_name": row["plan_name"], "identity_verified": row["identity_verified"], "runtime_name": row["runtime_name"], "digest": row["digest"], "artifact_sha256": row["artifact_sha256"], "blocker": row.get("network_failure")} for row in identities],
        "audit_timestamp_utc": generated_at,
    })
    for row in identities:
        write_json(OUT / f"{row['model_id']}_manifest.json", row)
    write_json(OUT / "historical_artifact_mapping.json", historical)

    candidate_digests = [row.get("digest") for row in identities]
    historical_judge_digest = historical["old_deepseek_r1_8b"]["digest"]
    write_json(OUT / "judge_manifest.json", {
        "selected_judge": "deepseek-r1:8b",
        "judge_model": "DeepSeek-R1-0528-Qwen3-8B",
        "model_tag": "deepseek-r1:8b",
        "judge_digest": historical_judge_digest,
        "artifact_source": "https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "source_revision": "upstream main revision not pinned in local Ollama artifact; local Ollama manifest digest freezes the artifact",
        "license": "MIT",
        "parameter_count": 8190735360,
        "quantization": "Q4_K_M",
        "architecture": "qwen3",
        "context_length": 131072,
        "tokenizer_identity": "Ollama GGUF tokenizer metadata sha256: 3a949d738b2bedf6a35aefc4d14a6284c44663a879c141be86b752db108989ca; tokenizer.ggml.model=gpt2; bos=151643; eos=151645",
        "artifact_size_bytes": 5225376047,
        "generation_parameters": {"temperature": 0, "top_p": 1, "seed": 20021, "num_predict": 8192, "num_ctx": 16384, "think": False},
        "runtime": "Ollama",
        "runtime_version": "0.35.0",
        "temperature": 0,
        "top_p": 1,
        "seed": 20021,
        "max_output_tokens": 8192,
        "structured_output_mode": "Ollama native JSON Schema from frozen RAGAS 0.4.3 metric prompts",
        "independent_judge_ready": False,
        "evaluation_only_role": True,
        "historical_phase17_generator_artifact": True,
        "not_candidate_M3": True,
        "evaluation_only": True,
        "candidate_digest_conflicts": [],
        "primary_phase16_judge_digest_not_selected": old_judge["primary_phase16_judge_digest"],
        "primary_phase16_judge": old_judge["primary_phase16_judge"],
        "primary_phase16_judge_digest": old_judge["primary_phase16_judge_digest"],
        "reason_for_reuse": "The installed historical Qwen3-based DeepSeek 8B artifact has a digest distinct from M1, M2, and the planned Llama-based M3 lineage, and is used only as the evaluation-only Judge. It is not used as candidate M3.",
        "independence_assessment": {
            "M1_digest_conflict": False,
            "M2_digest_conflict": False,
            "M4_digest_conflict": False,
            "M3_exact_digest": None,
            "planned_M3_architecture": "llama",
            "judge_architecture": "qwen3",
            "distinct_from_planned_M3_lineage": True,
            "all_four_local_candidate_digests_available": False,
        },
        "known_risk": "Phase 16 diagnostic showed output truncation at the prior 4096-token budget; Phase 20.1 uses a predeclared 8192-token Judge output limit and must pass calibration without truncation.",
        "network_access_status": "not_needed_existing_local_artifact",
    })
    phase17_rows = [json.loads(line) for line in phase17_outputs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    group_rows: dict[tuple[str, str], list[dict]] = {}
    for row in phase17_rows:
        if row.get("condition") in {"oracle", "e4_top5"} and row.get("status") == "answered" and row.get("generator") in {"deepseek-r1:7b", "qwen2.5-coder:7b", "gemma2:9b"}:
            group_rows.setdefault((row.get("generator"), row["condition"]), []).append(row)
    group_models = sorted({model for model, _ in group_rows})
    calibration: list[dict] = []
    mapping: list[dict] = []
    rng = random.Random(20021)
    # Fifteen Oracle and fifteen E4 outputs; five each from the three current
    # candidate artifacts that already have frozen Phase 17 outputs. Exclude
    # the historical DeepSeek 8B artifact because it is the Judge candidate.
    for condition in ("oracle", "e4_top5"):
        quotas = {model: 5 for model in group_models}
        for model in group_models:
            candidates = sorted(group_rows.get((model, condition), []), key=lambda row: row.get("question_id", ""))
            rng.shuffle(candidates)
            for row in candidates[:quotas[model]]:
                calibration_id = f"judge_cal_{len(calibration) + 1:02d}"
                payload = {
                    "calibration_id": calibration_id,
                    "question_id": row["question_id"],
                    "question": row.get("question"),
                    "condition": row.get("condition"),
                    "answer": row.get("answer"),
                    "status": row.get("status"),
                    "contexts": row.get("contexts", []),
                    "reference_answer": row.get("reference_answer"),
                    "benchmark_type": row.get("benchmark_type", "silver"),
                    "silver_reference": True,
                    "species": row.get("species"),
                    "category": row.get("category"),
                    "query_style": row.get("query_style"),
                    "required_evidence_complete_in_top5": row.get("required_evidence_complete_in_top5"),
                    "source_output_sha256": hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "generator_identity_withheld": True,
                }
                calibration.append(payload)
                mapping.append({"calibration_id": calibration_id, "source_generator": model, "condition": condition, "question_id": row["question_id"]})
    calibration_path = OUT / "judge_calibration_set.jsonl"
    calibration_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in calibration), encoding="utf-8")
    write_json(OUT / "judge_calibration_manifest.json", {
        "set_id": "phase20_1_judge_calibration_v1",
        "target_outputs": 30,
        "actual_outputs": len(calibration),
        "oracle_outputs": sum(row["condition"] == "oracle" for row in calibration),
        "e4_top5_outputs": sum(row["condition"] == "e4_top5" for row in calibration),
        "sampling_rule": "Phase 17 frozen answered outputs only; deterministic Python Random seed 20021; 5 outputs each from M1, M2, and M4 generator artifacts in each Oracle/E4 condition; the historical DeepSeek 8B Judge candidate is excluded from its own calibration set; no Phase 20 Selection or Holdout rows.",
        "seed": 20021,
        "source_path": "reports/evaluation/generation_models/phase17/per_question_metrics.jsonl",
        "source_sha256": sha256(phase17_outputs_path),
        "set_sha256": sha256(calibration_path),
        "generator_identity_withheld_from_judge_input": True,
        "judge_execution_status": "not_run_no_independent_judge",
    })
    write_json(OUT / "judge_calibration_source_map.json", {
        "purpose": "internal provenance only; do not include in Judge request",
        "rows": mapping,
        "group_counts": {f"{model}|{condition}": sum(item["source_generator"] == model and item["condition"] == condition for item in mapping) for model in group_models for condition in ("oracle", "e4_top5")},
    })
    write_json(OUT / "judge_preflight.json", {
        "status": "pending_calibration",
        "independent_judge_ready": False,
        "locally_available_completion_models": old_judge["locally_available_completion_models"],
        "calibration_target": 30,
        "first_pass_completed": 0,
        "second_pass_completed": 0,
        "completion_count_required": 60,
        "schema_parse_rate": None,
        "truncation_count": None,
        "technical_failure_count": None,
        "metrics_parseable": False,
        "calibration_executed": False,
        "calibration_set_path": "reports/evaluation/final_model_selection/phase20_1/judge_calibration_set.jsonl",
        "calibration_set_sha256": sha256(calibration_path),
        "reason": "Judge identity is independent of the planned candidates; readiness remains pending until both fixed calibration passes complete with no truncation or technical/schema failures.",
    })
    write_json(OUT / "judge_repeatability.json", {
        "status": "not_run_no_independent_judge",
        "outputs_per_pass": 30,
        "passes": 2,
        "completed_pairs": 0,
        "exact_agreement": None,
        "mean_absolute_difference": None,
        "pearson": None,
        "spearman": None,
        "human_validity_claim": False,
    })

    matrix = empty_evidence_matrix(scan_rows)
    matrix_payload = {
        "species": list(SPECIES), "categories": list(CATEGORIES),
        "cell_count": len(matrix), "target_ready_units_per_cell": 5,
        "ready_units_total": 0, "ready_cells": 0,
        "empty_cells": sum(row["prior_scan_status"] == "no_screened_chunk" for row in matrix),
        "review_needed_cells": sum(row["prior_scan_status"] == "review_required" for row in matrix),
        "question_count_confirmed": 0,
        "source_chunk_counts_are_not_question_counts": True,
        "prior_phase20_scan_sha256": sha256(GAP_PATH),
        "matrix": matrix,
        "status_note": "No evidence unit was promoted based on a chunk count. Each unit needs a distinct answerable fact/rule and explicit source review.",
    }
    write_json(OUT / "evidence_matrix.json", matrix_payload)
    (OUT / "evidence_units.jsonl").write_text("", encoding="utf-8")
    write_json(OUT / "evidence_gap_report.json", {
        "imported_phase20_scan": prior_gap,
        "imported_scan_path": "reports/evaluation/final_model_selection/phase20/evidence_coverage_gaps.json",
        "imported_scan_sha256": sha256(GAP_PATH),
        "normal_risk_evidence_pool_path": "data/evaluation/grounded/evidence_pool_v1.jsonl",
        "normal_risk_evidence_pool_sha256": sha256(POOL_PATH),
        "normal_risk_evidence_pool_chunks": 486,
        "source_verification_status_counts": {"verified": 216, "pending": 270},
        "question_ready_unit_count": 0,
        "warning": "The 486 and per-cell candidate counts are source/chunk screening counts, not validated evidence-unit or question counts.",
    })

    high_risk_rows = []
    for species in SPECIES:
        old = old_rows[(species, "Safe Medication / Law")]
        high_risk_rows.append({
            "species": species,
            "category": "Safe Medication / Law",
            "target_ready_units": 5,
            "screening_candidate_chunk_count": old["screening_candidate_chunk_count"],
            "ready_unit_count": 0,
            "review_status": "needs_review" if old["screening_candidate_chunk_count"] else "missing",
            "authority_document_page_version_applicability_checksum_reviewed": False,
            "reason": "No item-level current applicability and checksum review was recorded; source-screening count is insufficient to promote a high-risk unit.",
        })
    write_json(OUT / "high_risk_source_audit.json", {
        "allowed_source_types": ["verified official government source"],
        "required_fields": ["authority", "document title", "page", "date/version", "current applicability", "checksum"],
        "ready_units": 0,
        "ready": False,
        "species_cells": high_risk_rows,
    })
    (OUT / "calculation_evidence_registry.jsonl").write_text("", encoding="utf-8")
    write_json(OUT / "calculation_registry_status.json", {
        "target_units": 30,
        "target_per_species": 5,
        "ready_units": 0,
        "ready": False,
        "candidate_screening_chunk_counts": {species: old_rows[(species, "Calculation")]["screening_candidate_chunk_count"] for species in SPECIES},
        "candidate_screening_total": sum(old_rows[(species, "Calculation")]["screening_candidate_chunk_count"] for species in SPECIES),
        "expected_answers_from_candidate_llm": False,
        "reason": "No formulas were individually validated against evidence with deterministic inputs, units, rounding, and tolerance.",
    })

    write_json(OUT / "phase20_immutable_checksums.json", {
        "directory": "reports/evaluation/final_model_selection/phase20",
        "captured_at_utc": generated_at,
        "file_count": len(phase20_before),
        "files": phase20_before,
        "immutable": True,
    })
    write_json(OUT / "protected_database_before.json", {**db_before, "captured_at_utc": generated_at})
    write_json(OUT / "environment_and_acquisition.json", {
        "python_version": sys.version,
        "platform": platform.platform(),
        "ollama_models_seen": [item["model"] for item in old_judge["locally_available_completion_models"]],
        "noncandidate_local_completion_judge_available": False,
        "huggingface_direct_api": "blocked (WinError 10013); no workaround attempted",
        "model_downloads_or_installations": 0,
    })

    gates = {
        "model_identity_ready": all(row["identity_verified"] for row in identities),
        "judge_ready": False,
        "evidence_matrix_ready": False,
        "high_risk_ready": False,
        "calculation_ready": False,
    }
    write_json(OUT / "readiness.json", {
        **phase20_2_readiness(gates),
        "gates": gates,
        "four_models_ready": gates["model_identity_ready"],
        "independent_judge_ready": gates["judge_ready"],
        "evidence_matrix_ready": gates["evidence_matrix_ready"],
        "high_risk_ready": gates["high_risk_ready"],
        "calculation_ready": gates["calculation_ready"],
        "formal_candidate_ranking": False,
        "winner": None,
        "phase20_1_stops_at_readiness": True,
    })

    phase20_after = file_inventory(PHASE20)
    write_json(OUT / "phase20_immutable_check_result.json", {
        "unchanged": phase20_before == phase20_after,
        "before_file_count": len(phase20_before),
        "after_file_count": len(phase20_after),
        "changed_paths": sorted({x["path"] for x in phase20_before} ^ {x["path"] for x in phase20_after}) if phase20_before != phase20_after else [],
    })

    summary = f"""# RAG v2 Phase 20.1 — Final Evaluation Readiness Recovery

Generated: {generated_at}

## Scope and result

- AQUA-7B: excluded (`aqua7b_included=false`; reason: `revised experimental scope`). No download, deployment, test, ranking, or proxy was used.
- Four planned candidates only. M1 and M2 passed exact local digest rechecks. M4 lineage is tied to the official Gemma 2 9B-IT card and the matching official Ollama instruct Q4_0 tag. M3's required upstream lineage is identifiable, but no exact local Q4 GGUF was acquired; M3 remains blocked. The old Qwen3-based `deepseek-r1:8b` remains historical-only.
- `four_models_ready=false`; no independent Judge artifact was available, so calibration was not run and `independent_judge_ready=false`.
- The imported Phase 20 scan remains 486 normal-risk chunks, 15 empty cells, and 21 review-needed cells. These are screening counts, not question counts. No question-ready unit has yet passed item-level review: 0/36 cells meet the target of five.
- High-risk ready units: 0. Calculation registry: 0/30 deterministic units. No Candidate LLM supplied calculation answers.
- `phase20_2_benchmark_construction_ready=false`. No formal ranking, Winner, Selection requests, or Holdout evaluation was produced.

## Gate status

| Gate | Ready | Reason |
|---|---:|---|
| Model identity | No | Exact M3 GGUF artifact unavailable |
| Independent Judge | No | No non-candidate local evaluator; model-host access blocked |
| Evidence matrix | No | No reviewed question-ready evidence units |
| High-risk sources | No | Item-level current applicability and checksum reviews missing |
| Calculation registry | No | No formulas validated as deterministic units |

## Source and compatibility notes

The original Phase 20 directory was inventoried before and after report generation; see `phase20_immutable_check_result.json`. The production SQLite database baseline is in `protected_database_before.json`; a final compatibility check is recorded separately after the application smoke check.

M3 upstream lineage source: [official DeepSeek Distill-Llama-8B model card](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-8B). M4 lineage sources: [Google Gemma 2 9B-IT model card](https://huggingface.co/google/gemma-2-9b-it) and [official Ollama Gemma 2 tags](https://ollama.com/library/gemma2/tags).
"""
    (OUT / "phase20_1_summary.md").write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
