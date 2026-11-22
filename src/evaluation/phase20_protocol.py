"""Frozen gates and scoring rules for the Phase 20 four-model study."""

from __future__ import annotations

from collections import Counter
from random import Random
from typing import Any, Iterable


PHASE20_CANDIDATES = (
    {
        "model_id": "M1",
        "plan_name": "DeepSeek-R1-Distill-Qwen-7B",
        "runtime_name": "deepseek-r1:7b",
        "architecture": "qwen2",
        "basename_contains": "DeepSeek-R1-Distill-Qwen",
    },
    {
        "model_id": "M2",
        "plan_name": "Qwen 2.5-Coder-7B-Instruct",
        "runtime_name": "qwen2.5-coder:7b",
        "architecture": "qwen2",
        "basename_contains": "Qwen2.5-Coder",
        "finetune": "Instruct",
    },
    {
        "model_id": "M3",
        "plan_name": "DeepSeek-R1-Distill-Llama-8B",
        "runtime_name": "deepseek-r1:8b",
        "architecture": "llama",
        "basename_contains": "DeepSeek-R1-Distill-Llama",
    },
    {
        "model_id": "M4",
        "plan_name": "Gemma 2 (9B-It)",
        "runtime_name": "gemma2:9b",
        "architecture": "gemma2",
        "parameter_count_min": 8_500_000_000,
        "parameter_count_max": 10_000_000_000,
        "finetune": "It",
    },
)

SPECIES = ("虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚")
CATEGORIES = (
    "Fact",
    "Water Quality",
    "Disease",
    "Climate / Cold",
    "Safe Medication / Law",
    "Calculation",
)
QUERY_STYLES = ("Direct", "Paraphrase", "Contextual")
WORKBOOK_SHEETS = (
    "00_README",
    "01_Model_Identity",
    "02_Metric_Definitions",
    "03_Overall_Summary",
    "04_Faithfulness",
    "05_Answer_Relevance",
    "06_Context_Precision",
    "07_Logic_Arithmetic",
    "08_Instruction_Following",
    "09_Edge_Performance",
    "10_Per_Species",
    "11_Per_Category",
    "12_Per_Query_Style",
    "13_Raw_Selection",
    "14_Edge_Raw_Runs",
    "15_Eligibility",
    "16_Selection_Score",
    "17_Sensitivity",
    "18_Final_Ranking",
    "19_Final_Holdout",
    "20_Final_System",
)

QUALITY_WEIGHTS = {
    "faithfulness": 0.175,
    "plan_answer_relevance": 0.175,
    "arithmetic_accuracy": 0.175,
    "plan_ifr": 0.175,
}
EDGE_WEIGHTS = {"ttft_ms": 0.10, "tps": 0.10, "memory_pressure": 0.10}
CONTEXT_PRECISION_WEIGHT = 0.0
SENSITIVITY_SPLITS = ((0.60, 0.40), (0.70, 0.30), (0.80, 0.20))


def scope_change() -> dict[str, Any]:
    return {
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
    }


def identity_issues(candidate: dict[str, Any], artifact: dict[str, Any]) -> list[str]:
    """Compare source/model metadata; a matching runtime tag is not sufficient."""
    issues: list[str] = []
    if artifact.get("runtime_name") != candidate["runtime_name"]:
        issues.append("runtime_name_mismatch")
    if artifact.get("architecture") != candidate["architecture"]:
        issues.append("architecture_mismatch")
    expected_base = candidate.get("basename_contains")
    if expected_base and expected_base not in str(artifact.get("basename") or ""):
        issues.append("base_model_metadata_mismatch_or_missing")
    expected_finetune = candidate.get("finetune")
    if expected_finetune and str(artifact.get("finetune") or "").casefold() != expected_finetune.casefold():
        issues.append("instruction_finetune_metadata_unverified")
    if "parameter_count_min" in candidate:
        count = artifact.get("parameter_count")
        if not isinstance(count, (int, float)) or not (
            candidate["parameter_count_min"] <= count <= candidate["parameter_count_max"]
        ):
            issues.append("parameter_count_mismatch")
    for field in ("digest", "quantization", "artifact_size_bytes", "context_length", "source_metadata"):
        if artifact.get(field) in (None, ""):
            issues.append(f"missing_{field}")
    return issues


def four_models_ready(identity_rows: Iterable[dict[str, Any]]) -> bool:
    rows = list(identity_rows)
    return len(rows) == 4 and all(row.get("identity_verified") is True for row in rows)


def plan_ifr(valid_structured_outputs: int, all_requests: int) -> float | None:
    if all_requests <= 0:
        return None
    return valid_structured_outputs / all_requests


def tps_comparable(model_rows: Iterable[dict[str, Any]]) -> bool:
    rows = list(model_rows)
    if len(rows) != 4:
        return False
    semantics = {row.get("tps_definition") for row in rows}
    return len(semantics) == 1 and None not in semantics and all(
        row.get("reasoning_separation_reliable") is True for row in rows
    )


def selection_eligibility(gates: dict[str, Any]) -> dict[str, Any]:
    requirements = {
        "four_model_identity_verified": gates.get("four_models_ready") is True,
        "selection_120_completed": gates.get("selection_question_count") == 120
        and gates.get("selection_completed") is True,
        "primary_metrics_available": gates.get("all_primary_metrics_available") is True,
        "independent_judge_available": gates.get("independent_judge_ready") is True,
        "no_oom": gates.get("no_oom") is True,
        "no_unrecovered_runtime_crash": gates.get("no_unrecovered_runtime_crash") is True,
        "no_context_capacity_failure": gates.get("no_context_capacity_failure") is True,
        "plan_ifr_at_least_0_99": isinstance(gates.get("plan_ifr_min"), (int, float))
        and gates["plan_ifr_min"] >= 0.99,
        "performance_benchmark_complete": gates.get("performance_benchmark_complete") is True,
        "primary_tps_comparable": gates.get("primary_tps_comparable") is True,
    }
    failed = [key for key, passed in requirements.items() if not passed]
    return {
        "final_selection_eligible": not failed,
        "requirements": requirements,
        "failed_gates": failed,
    }


def minmax(values: dict[str, float], direction: str) -> dict[str, float]:
    """Fixed candidate-set min-max normalization; cost metrics are inverted."""
    if direction not in {"benefit", "cost"}:
        raise ValueError("direction must be benefit or cost")
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: 1.0 for key in values}
    if direction == "benefit":
        return {key: (value - low) / (high - low) for key, value in values.items()}
    return {key: (high - value) / (high - low) for key, value in values.items()}


def choose_winner(
    model_rows: list[dict[str, Any]],
    *,
    global_ready: bool,
    tolerance: float = 1e-12,
) -> dict[str, Any] | None:
    """Return a winner only when every candidate is eligible and has a score."""
    if not global_ready or len(model_rows) != 4:
        return None
    if any(row.get("final_selection_eligible") is not True for row in model_rows):
        return None
    if any(not isinstance(row.get("primary_score"), (int, float)) for row in model_rows):
        return None
    ordered = sorted(model_rows, key=lambda row: row["primary_score"], reverse=True)
    top_score = ordered[0]["primary_score"]
    tied = [row for row in ordered if top_score - row["primary_score"] <= tolerance]
    if len(tied) == 1:
        return tied[0]
    tie_order = (
        "quality_score",
        "arithmetic_accuracy",
        "faithfulness",
        "plan_ifr",
    )
    for key in tie_order:
        if all(isinstance(row.get(key), (int, float)) for row in tied):
            best = max(row[key] for row in tied)
            tied = [row for row in tied if row[key] == best]
            if len(tied) == 1:
                return tied[0]
    return min(tied, key=lambda row: row.get("ttft_ms", float("inf")))


def split_questions(questions: list[dict[str, Any]], seed: int = 20020) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic 120/60 split, fixing 20/10 per species before filling."""
    if len(questions) != 180:
        raise ValueError("Plan-Aligned benchmark must contain exactly 180 validated questions")
    if any(q.get("species") not in SPECIES for q in questions):
        raise ValueError("Every question must have a planned species")
    by_species: dict[str, list[dict[str, Any]]] = {species: [] for species in SPECIES}
    for question in questions:
        by_species[question["species"]].append(question)
    if any(len(items) != 30 for items in by_species.values()):
        raise ValueError("Each species must have exactly 30 evidence-valid questions")
    rng = Random(seed)
    selection: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    for species in SPECIES:
        items = list(by_species[species])
        rng.shuffle(items)
        selection.extend(items[:20])
        holdout.extend(items[20:])
    rng.shuffle(selection)
    rng.shuffle(holdout)
    return selection, holdout


def holdout_integrity(selection_ids: Iterable[str], holdout_ids: Iterable[str], evaluated_ids: Iterable[str]) -> bool:
    selection, holdout, evaluated = set(selection_ids), set(holdout_ids), set(evaluated_ids)
    return not (selection & holdout) and not (holdout & evaluated)


def metric_weights() -> dict[str, Any]:
    return {
        "quality": QUALITY_WEIGHTS,
        "edge": EDGE_WEIGHTS,
        "context_precision": CONTEXT_PRECISION_WEIGHT,
        "context_precision_non_discriminating": True,
    }


def independent_judge_independent(judge_digest: str | None, candidates: Iterable[dict[str, Any]]) -> bool:
    digests = {row.get("digest") for row in candidates}
    return bool(judge_digest) and judge_digest not in digests


def validate_calculation_record(record: dict[str, Any]) -> list[str]:
    required = ("formula", "input", "unit", "expected_numeric_output", "rounding", "tolerance", "evidence")
    issues = [f"missing_{field}" for field in required if record.get(field) in (None, "")]
    if record.get("gold_answer_source") == "candidate_llm":
        issues.append("candidate_llm_cannot_create_numeric_gold")
    if record.get("expected_numeric_output") is not None and not isinstance(
        record.get("expected_numeric_output"), (int, float)
    ):
        issues.append("expected_numeric_output_not_numeric")
    return issues


def common_config_issues(model_configs: Iterable[dict[str, Any]]) -> list[str]:
    rows = list(model_configs)
    if len(rows) != 4:
        return ["expected_four_model_configs"]
    required_fields = ("prompt_sha256", "schema_sha256", "temperature", "top_p", "seed", "max_output", "context")
    issues: list[str] = []
    for field in required_fields:
        values = {row.get(field) for row in rows}
        if None in values or len(values) != 1:
            issues.append(f"non_common_or_missing_{field}")
    return issues


def quality_edge_scores(metrics_by_model: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Normalize a complete candidate set and calculate the frozen 70/30 score."""
    if len(metrics_by_model) != 4:
        raise ValueError("Scoring requires exactly four candidate models")
    benefits = ("faithfulness", "plan_answer_relevance", "arithmetic_accuracy", "plan_ifr", "tps")
    costs = ("ttft_ms", "memory_pressure")
    for model, metrics in metrics_by_model.items():
        for key in benefits + costs:
            if not isinstance(metrics.get(key), (int, float)):
                raise ValueError(f"Missing primary metric {key} for {model}")
    normalized: dict[str, dict[str, float]] = {model: {} for model in metrics_by_model}
    for key in benefits:
        raw = {model: metrics[key] for model, metrics in metrics_by_model.items()}
        values = minmax(raw, "benefit")
        for model, value in values.items():
            normalized[model][key] = value
    for key in costs:
        raw = {model: metrics[key] for model, metrics in metrics_by_model.items()}
        values = minmax(raw, "cost")
        for model, value in values.items():
            normalized[model][key] = value
    result: dict[str, dict[str, float]] = {}
    for model in metrics_by_model:
        quality = sum(normalized[model][key] * weight for key, weight in QUALITY_WEIGHTS.items())
        edge = sum(normalized[model][key] * weight for key, weight in EDGE_WEIGHTS.items())
        result[model] = {
            "quality_score": quality,
            "edge_score": edge,
            "primary_score": 0.70 * quality + 0.30 * edge,
            "normalized": normalized[model],
        }
    return result


def phase21_readiness(
    *, four_models_completed: bool, independent_judge_ready: bool, all_primary_metrics_complete: bool,
    workbook_complete: bool, eligible_winner_exists: bool,
) -> dict[str, bool]:
    ready = all((four_models_completed, independent_judge_ready, all_primary_metrics_complete,
                 workbook_complete, eligible_winner_exists))
    return {"final_model_selection_ready": ready, "phase21_final_system_ready": ready}
