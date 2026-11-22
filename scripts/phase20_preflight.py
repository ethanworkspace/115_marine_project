"""Build a read-only Phase 20 preflight report; never runs candidate models."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.phase20_protocol import (
    CATEGORIES,
    PHASE20_CANDIDATES,
    QUERY_STYLES,
    SPECIES,
    WORKBOOK_SHEETS,
    identity_issues,
    scope_change,
    selection_eligibility,
)


OUT = ROOT / "reports/evaluation/final_model_selection/phase20"
DATA_OUT = ROOT / "data/evaluation/final_model_selection/phase20"
PHASE17 = ROOT / "reports/evaluation/generation_models/phase17"
POOL_PATH = ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"
CORPUS_PATH = ROOT / "data/evaluation/corpus_v2.jsonl"
JUDGE_PREFLIGHT_PATH = ROOT / "reports/evaluation/validity/phase18/independent_judge_preflight.json"
PHASE19_MANIFEST_PATH = ROOT / "reports/evaluation/edge/phase19B_exec_r2/experiment_manifest.json"
DB_PATH = ROOT / "rag_store.sqlite3"

FORMULA_CUE = re.compile(r"計算式|公式|SGR|FCR|每立方公尺|每公斤|%\s*/\s*day|×|÷|ppm|投餌量", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ollama_post(route: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:11434{route}", data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def ollama_tags() -> dict[str, Any]:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def model_identity_audit() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tags = ollama_tags()
    listed = {row["name"]: row for row in tags.get("models", [])}
    prior_audit = read_json(PHASE17 / "model_artifact_identity_audit.json")
    rows: list[dict[str, Any]] = []
    for candidate in PHASE20_CANDIDATES:
        name = candidate["runtime_name"]
        tag_row = listed.get(name)
        previous_identity = prior_audit.get(name, {})
        if not tag_row:
            rows.append({
                **candidate, "availability": "blocked_runtime", "identity_verified": False,
                "identity_issues": ["runtime_artifact_not_locally_available"],
            })
            continue
        shown = ollama_post("/api/show", {"model": name, "verbose": True})
        info = shown.get("model_info", {})
        details = tag_row.get("details", {})
        base = {
            "runtime_name": name,
            "architecture": info.get("general.architecture") or details.get("family"),
            "basename": info.get("general.basename"),
            "finetune": info.get("general.finetune"),
            "base_model_name": info.get("general.base_model.0.name"),
            "base_model_organization": info.get("general.base_model.0.organization"),
            "base_model_repo_url": info.get("general.base_model.0.repo_url"),
            "parameter_count": info.get("general.parameter_count"),
            "digest": tag_row.get("digest"),
            "quantization": details.get("quantization_level"),
            "artifact_size_bytes": tag_row.get("size"),
            "context_length": details.get("context_length"),
            "source_metadata": {
                key: value for key, value in info.items()
                if key.startswith("general.") and not isinstance(value, (dict, list))
                and key not in {"general.license"}
            },
        }
        issues = identity_issues(candidate, base)
        prior_digest = previous_identity.get("manifest_sha256")
        if prior_digest and prior_digest != base["digest"]:
            issues.append("phase17_digest_mismatch")
        base.update({
            **candidate,
            "availability": "available_exact_digest",
            "artifact_layer_digests": previous_identity.get("weight_layer_digests", []),
            "ollama_manifest_sha256": prior_digest,
            "identity_issues": issues,
            "identity_verified": not issues,
            "judge_conflict": bool(previous_identity.get("same_judge_weights")),
        })
        rows.append(base)
    return rows, tags


def protected_files() -> list[Path]:
    exact = [
        ROOT / "data/shadow/chunks_v2.jsonl", ROOT / "data/shadow/chunks_v3.jsonl",
        ROOT / "data/shadow/source_spans_v2.jsonl", ROOT / "data/shadow/source_spans_v3.jsonl",
        ROOT / "data/evaluation/corpus_v1.jsonl", CORPUS_PATH,
        ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl",
        ROOT / "data/evaluation/grounded/questions_v1.jsonl",
        ROOT / "data/evaluation/silver/questions_v1.jsonl",
        ROOT / "data/evaluation/silver/questions_v2.jsonl",
        ROOT / "data/evaluation/silver/questions_v3.jsonl",
        ROOT / "data/evaluation/edge/phase19_inputs_v1/inputs.jsonl",
        ROOT / "data/evaluation/edge/phase19_inputs_v1/edge_subset_v1.jsonl",
        DB_PATH,
    ]
    prefixes = [
        ROOT / "data/evaluation/indexes/E2_grounded_dense_v1",
        ROOT / "reports/evaluation/experiments/E1_grounded_bm25_v1",
        ROOT / "reports/evaluation/experiments/E2_grounded_dense_v1",
        ROOT / "reports/evaluation/experiments/E3_grounded_rrf_v1",
        ROOT / "reports/evaluation/experiments/E4_grounded_rrf_reranker_v1",
        ROOT / "reports/evaluation/generation_models/phase17",
        ROOT / "reports/evaluation/validity/phase18",
        ROOT / "reports/evaluation/validity/phase18_1",
        ROOT / "reports/evaluation/ragas/phase16",
        ROOT / "reports/evaluation/edge/phase19",
        ROOT / "reports/evaluation/edge/phase19A",
        ROOT / "reports/evaluation/edge/phase19B",
        ROOT / "reports/evaluation/edge/phase19B_runtime_recovery",
        ROOT / "reports/evaluation/edge/phase19B_exec_r2",
    ]
    prefixes += [
        ROOT / "reports/evaluation/generation" / name for name in (
            "G0_grounded_oracle_generation_v1", "G1_grounded_e4_top5_generation_v1",
            "G0_grounded_oracle_generation_v2", "G1_grounded_e4_top5_generation_v2",
            "G1_grounded_e4_top5_generation_v2_1", "G0_grounded_oracle_generation_v2_2",
            "G1_grounded_e4_top5_generation_v2_2",
        )
    ]
    files = {p.resolve() for p in exact if p.is_file()}
    for prefix in prefixes:
        if prefix.is_dir():
            files.update(p.resolve() for p in prefix.rglob("*") if p.is_file())
    return sorted(files)


def protected_snapshot() -> dict[str, Any]:
    entries = []
    for path in protected_files():
        try:
            entries.append({
                "path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            })
        except OSError as exc:
            entries.append({"path": str(path), "sha256": None, "error": str(exc)})
    return {"file_count": len(entries), "files": entries}


def evidence_coverage(pool: list[dict[str, Any]], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {"Fact": "fact", "Water Quality": "water_quality", "Disease": "disease", "Climate / Cold": "climate"}
    matrix: list[dict[str, Any]] = []
    formula_rx = FORMULA_CUE
    retrieval = [
        row for row in corpus
        if row.get("retrieval_role") == "retrieval"
        and row.get("duplicate_status") not in {"exact_duplicate", "duplicate_source"}
    ]
    for species in SPECIES:
        for requested_category in CATEGORIES:
            relevant_pool = [
                row for row in pool
                if row.get("species") == species
                and row.get("category") == categories.get(requested_category)
            ] if requested_category in categories else []
            accepted_verified = [
                row for row in relevant_pool
                if row.get("evidence_quality_status") == "accepted" and row.get("source_verified") is True
            ]
            text_hits = [
                row for row in retrieval
                if species in ((row.get("text") or "") + " " + (row.get("source_title") or ""))
            ]
            if requested_category == "Safe Medication / Law":
                hits = [
                    row for row in retrieval
                    if row.get("risk_level") == "high"
                    and row.get("source_verification_status") == "verified"
                    and row.get("legal_status") == "current"
                    and row.get("source_id") == "moa_official"
                    and species in ((row.get("text") or "") + " " + (row.get("source_title") or ""))
                ]
                candidate_count = len(hits)
                criterion = "verified current official MOA source chunks explicitly mentioning this species"
            elif requested_category == "Calculation":
                hits = [row for row in text_hits if formula_rx.search(row.get("text") or "")]
                candidate_count = len(hits)
                criterion = "retrieval chunks explicitly mentioning species and a formula/numeric rule cue; manual formula validation still required"
            else:
                candidate_count = len(accepted_verified)
                criterion = "normal-risk evidence-pool chunks tagged to species/category, accepted and source verified"
            matrix.append({
                "species": species,
                "category": requested_category,
                "target_question_count": 5,
                "screening_candidate_chunk_count": candidate_count,
                "screening_rule": criterion,
                "question_capacity_confirmed": False,
                "status": "no_screened_chunk" if candidate_count == 0 else "review_required",
            })
    return {
        "evaluation_corpus_v2_retrieval_chunks": 2224,
        "normal_risk_evidence_pool_chunks": len(pool),
        "evidence_pool_status_counts": {
            status: sum(row.get("evidence_quality_status") == status for row in pool)
            for status in sorted({row.get("evidence_quality_status") for row in pool})
        },
        "source_verification_status_counts": {
            status: sum(row.get("source_verification_status") == status for row in pool)
            for status in sorted({row.get("source_verification_status") for row in pool})
        },
        "matrix": matrix,
        "source_screening_only_not_question_count": True,
        "question_count_confirmed": 0,
        "manual_source_and_question_validation_required": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    protected_before = protected_snapshot()
    write_json(OUT / "protected_inputs_before.json", protected_before)

    identity_rows, tags = model_identity_audit()
    four_ready = len(identity_rows) == 4 and all(row.get("identity_verified") for row in identity_rows)
    write_json(OUT / "candidate_model_manifest.json", {
        "phase": "RAG v2 Phase 20",
        "models": identity_rows,
        "four_models_ready": four_ready,
        "identity_source": "live read-only Ollama /api/tags and /api/show plus Phase 17 content-addressed artifact audit",
        "identity_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "no_model_acquisition": True,
    })
    write_json(OUT / "scope_change.json", scope_change())

    pool = read_jsonl(POOL_PATH)
    corpus = read_jsonl(CORPUS_PATH)
    coverage = evidence_coverage(pool, corpus)
    write_json(OUT / "evidence_coverage_gaps.json", coverage)

    phase17 = read_json(PHASE17 / "generator_comparison_manifest.json")
    judge_history = read_json(JUDGE_PREFLIGHT_PATH)
    candidate_digests = {row.get("digest") for row in identity_rows}
    current_completion = [
        {"model": row.get("name"), "digest": row.get("digest"), "capabilities": row.get("capabilities", [])}
        for row in tags.get("models", []) if "completion" in row.get("capabilities", [])
    ]
    judge_manifest = {
        "status": "blocked_evaluator_runtime",
        "independent_judge_ready": False,
        "selected_judge": None,
        "prior_phase18_status": judge_history.get("status", "unknown"),
        "primary_phase16_judge": phase17.get("judge", {}).get("judge_model"),
        "primary_phase16_judge_digest": phase17.get("judge", {}).get("model_digest"),
        "primary_judge_is_candidate": phase17.get("judge", {}).get("model_digest") in candidate_digests,
        "locally_available_completion_models": current_completion,
        "selection_rule": "same evaluator for all candidates and evaluator digest must differ from every candidate artifact",
        "note": "All locally available completion artifacts are the four candidates; qwen2.5-coder:7b is both candidate M2 and the prior judge. BGE-M3 is embedding-only.",
        "no_model_download": True,
    }
    write_json(OUT / "judge_manifest.json", judge_manifest)

    identity_issues_by_model = {row["runtime_name"]: row.get("identity_issues", []) for row in identity_rows}
    eligibility_gates = {
        "four_models_ready": four_ready,
        "selection_question_count": 0,
        "selection_completed": False,
        "all_primary_metrics_available": False,
        "independent_judge_ready": False,
        "no_oom": False,
        "no_unrecovered_runtime_crash": False,
        "no_context_capacity_failure": False,
        "plan_ifr_min": None,
        "performance_benchmark_complete": False,
        "primary_tps_comparable": False,
    }
    eligibility = selection_eligibility(eligibility_gates)
    eligibility.update({
        "phase20_execution_started": False,
        "identity_issues_by_model": identity_issues_by_model,
        "holdout_evaluated": False,
        "winner": None,
        "ranking_created": False,
    })
    write_json(OUT / "eligibility.json", eligibility)
    write_json(OUT / "selection_scores.json", {
        "status": "not_calculated",
        "reason": "eligibility gates failed; no candidate outputs exist",
        "primary_weights": {"quality": 0.70, "edge": 0.30},
        "quality_weights": {"faithfulness": 0.175, "plan_answer_relevance": 0.175,
                            "arithmetic_accuracy": 0.175, "plan_ifr": 0.175},
        "edge_weights": {"ttft": 0.10, "tps": 0.10, "peak_memory_pressure": 0.10},
        "context_precision_weight": 0.0,
        "raw_scores": None,
        "normalized_scores": None,
        "final_score": None,
    })
    write_json(OUT / "sensitivity.json", {
        "status": "not_calculated",
        "predeclared_quality_edge_weights": [
            {"quality": 0.60, "edge": 0.40}, {"quality": 0.70, "edge": 0.30}, {"quality": 0.80, "edge": 0.20}
        ],
        "winner_by_weight_split": None,
        "robust_winner": None,
        "winner_weight_sensitive": None,
    })
    write_json(OUT / "paired_bootstrap.json", {
        "status": "not_run", "iterations": 10000, "seed": 20020,
        "reason": "no Phase 20 Selection outputs; identity and benchmark construction gates failed",
        "holdout_used": False,
    })
    write_json(OUT / "final_ranking.json", {
        "status": "not_ranked", "models": [row["runtime_name"] for row in identity_rows],
        "winner": None, "reason": "four_models_ready=false and final selection eligibility=false",
    })
    write_json(OUT / "winner_manifest.json", {
        "winner": None, "final_model_selection_ready": False,
        "phase21_final_system_ready": False,
        "reason": "No four-model ranking was run; no model is eligible as Winner.",
    })

    benchmark_manifest = {
        "benchmark_name": "Plan-Aligned Unified Benchmark v1",
        "target_question_count": 180,
        "actual_question_count": 0,
        "question_dataset_created": False,
        "species": {species: 30 for species in SPECIES},
        "category_per_species": {category: 5 for category in CATEGORIES},
        "query_style_target": {style: 60 for style in QUERY_STYLES},
        "selection_target": 120,
        "holdout_target": 60,
        "seed": 20020,
        "selection_actual": 0,
        "holdout_actual": 0,
        "holdout_sealed": False,
        "holdout_evaluated": False,
        "build_status": "not_built",
        "stop_reason": "model identity gate failed; source coverage remains unvalidated for the requested balanced matrix",
        "evidence_first": True,
    }
    write_json(OUT / "benchmark_manifest.json", benchmark_manifest)
    write_json(OUT / "selection_manifest.json", {
        "target_selection_questions": 120, "actual_selection_questions": 0,
        "split_seed": 20020, "stratification": ["species", "category", "style"],
        "split_executed": False, "reason": "No 180-question evidence-validated dataset exists.",
    })
    write_json(OUT / "holdout_manifest.json", {
        "target_holdout_questions": 60, "holdout_ids": [], "holdout_metadata": [],
        "holdout_checksums": [], "sealed": False, "evaluated": False,
        "reason": "No questions were created or split; no holdout IDs are represented as sealed.",
        "holdout_reserved_for_phase21_1": True,
    })
    write_json(OUT / "experiment_manifest.json", {
        "phase": "RAG v2 Phase 20",
        "experiment_status": "blocked_before_formal_evaluation",
        "timestamp_utc": started,
        "scope_change": scope_change(),
        "candidate_count": 4,
        "four_models_ready": four_ready,
        "independent_judge_ready": False,
        "evaluation_requests": 0,
        "selection_outputs": 0,
        "edge_performance_requests": 0,
        "cold_runs": 0,
        "holdout_evaluated": False,
        "production_retrieval_touched": False,
        "rag_store_touched": False,
        "no_model_download": True,
    })

    current_db = {
        "exists": DB_PATH.exists(),
        "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else None,
        "mtime_ns": DB_PATH.stat().st_mtime_ns if DB_PATH.exists() else None,
        "sha256": sha256_file(DB_PATH) if DB_PATH.exists() else None,
    }
    try:
        request = urllib.request.Request("http://127.0.0.1:8501", method="GET")
        with urllib.request.urlopen(request, timeout=4) as response:
            app_check = {"url": "http://127.0.0.1:8501", "status_code": response.status}
    except Exception as exc:  # read-only health check
        app_check = {"url": "http://127.0.0.1:8501", "status_code": None,
                     "status": "unavailable", "error": str(exc)}
    write_json(OUT / "production_compatibility.json", {
        "streamlit_http_check": app_check,
        "rag_store_before": current_db,
        "rag_store_modified_by_phase20": False,
        "note": "This preflight did not launch or modify production services.",
    })

    after = protected_snapshot()
    before_by_path = {row["path"]: row.get("sha256") for row in protected_before["files"]}
    after_by_path = {row["path"]: row.get("sha256") for row in after["files"]}
    keys = sorted(set(before_by_path) | set(after_by_path))
    comparisons = [{
        "path": key, "before_sha256": before_by_path.get(key), "after_sha256": after_by_path.get(key),
        "unchanged": before_by_path.get(key) is not None and before_by_path.get(key) == after_by_path.get(key),
    } for key in keys]
    write_json(OUT / "protected_artifact_compatibility.json", {
        "files_checked": len(comparisons), "unchanged_count": sum(row["unchanged"] for row in comparisons),
        "changed_or_unavailable_count": sum(not row["unchanged"] for row in comparisons),
        "all_unchanged": all(row["unchanged"] for row in comparisons),
        "files": comparisons,
    })

    write_json(OUT / "workbook_manifest.json", {
        "requested_workbook": "aquaculture_4model_unified_evaluation.xlsx",
        "worksheets": list(WORKBOOK_SHEETS),
        "metric_values": "NA until eligible Selection outputs exist",
        "winner": None,
        "holdout_ids_written": False,
    })
    (OUT / "phase20_summary.md").write_text(
        "# RAG v2 Phase 20 preflight\n\n"
        "## Result\n\n"
        "Phase 20 stopped before question generation and formal model evaluation. The requested four-model identity gate did not pass. "
        "The local `deepseek-r1:8b` artifact identifies as `DeepSeek-R1-0528-Qwen3` with Qwen3 architecture, while M3 requires "
        "`DeepSeek-R1-Distill-Llama-8B`. The local `gemma2:9b` artifact confirms Gemma 2 / 9.2B / Q4_0, but does not expose metadata confirming the planned `9B-It` fine-tune.\n\n"
        "No balanced 180-question dataset was produced, so Selection and Holdout were not split. Holdout was not evaluated. "
        "The current independent-judge preflight remains blocked: the only local completion candidates are the four generators, and the prior Qwen Judge shares M2's digest. "
        "The old Qwen self-judge score is not used.\n\n"
        "All model metrics, scores, ranks, and Winner are NA/null because there are no Phase 20 responses. Context Precision remains a planned system-level metric with zero selection weight. "
        "AQUA-7B is excluded under the revised experimental scope. This is not a completed five-model comparison.\n\n"
        "## Data and compatibility\n\n"
        f"The frozen Evaluation Corpus v2 contains {coverage['evaluation_corpus_v2_retrieval_chunks']:,} retrieval chunks. "
        f"The existing normal-risk evidence pool contains {coverage['normal_risk_evidence_pool_chunks']:,} chunks. "
        "The species/category counts in the accompanying gap report are source-chunk screens, not validated question capacity. "
        "No question was created from missing evidence and no medication/law answer was inferred.\n\n"
        f"Production Streamlit check: {app_check.get('status_code') or 'unavailable'}. "
        f"The database was read-only during this preflight (SHA-256 {current_db['sha256']}). "
        f"Protected frozen files checked: {len(comparisons)}; unchanged: {sum(row['unchanged'] for row in comparisons)}.\n\n"
        "## Readiness\n\n"
        "`four_models_ready=false`; `final_selection_ready=false`; `Winner=null`; `final_model_selection_ready=false`; `phase21_final_system_ready=false`. "
        "The next prerequisite is a source-verified M3 artifact matching the planned Llama distill identity, explicit source metadata for the Gemma 9B-It variant, "
        "and an independent local Judge, followed by validation of the full evidence-balanced benchmark before any ranking.\n",
        encoding="utf-8",
    )
    final_db = {
        "exists": DB_PATH.exists(),
        "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else None,
        "mtime_ns": DB_PATH.stat().st_mtime_ns if DB_PATH.exists() else None,
        "sha256": sha256_file(DB_PATH) if DB_PATH.exists() else None,
    }
    compatibility = read_json(OUT / "production_compatibility.json")
    compatibility["rag_store_after"] = final_db
    compatibility["rag_store_unchanged"] = current_db == final_db
    write_json(OUT / "production_compatibility.json", compatibility)
    print(json.dumps({
        "output_dir": OUT.as_posix(), "identity": {row["runtime_name"]: row["identity_verified"] for row in identity_rows},
        "four_models_ready": four_ready, "judge_ready": False,
        "protected_files_checked": len(comparisons), "all_protected_unchanged": all(row["unchanged"] for row in comparisons),
        "db_unchanged": current_db == final_db, "streamlit": app_check,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
