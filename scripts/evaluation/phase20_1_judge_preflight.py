"""Run the fixed Phase 20.1 Judge calibration set twice with the local Judge."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1"
SET_PATH = OUT / "judge_calibration_set.jsonl"
MANIFEST_PATH = OUT / "judge_calibration_manifest.json"
RAW_PATH = OUT / "judge_calibration_raw_outputs.jsonl"
SCORE_PATH = OUT / "judge_calibration_scores.jsonl"
JUDGE_MODEL = "deepseek-r1:8b"
JUDGE_DIGEST = "6995872bfe4c521a67b32da386cd21d5c6e819b6e0d62f79f64ec83be99f5763"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
OPTIONS = {"temperature": 0, "top_p": 1, "seed": 20021, "num_predict": 8192, "num_ctx": 16384}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2
        for offset in range(start, end):
            ranks[order[offset]] = average
        start = end
    return ranks


def correlation(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return numerator / (da * db) if da and db else None


def main() -> None:
    if RAW_PATH.exists() or SCORE_PATH.exists():
        raise SystemExit("Refusing to overwrite existing Phase 20.1 Judge calibration results.")
    if importlib.metadata.version("ragas") != "0.4.3":
        raise SystemExit("blocked_exact_evaluator_runtime: RAGAS version is not 0.4.3")
    import requests

    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=20)
    tags.raise_for_status()
    models = {row["name"]: row for row in tags.json().get("models", [])}
    if models.get(JUDGE_MODEL, {}).get("digest") != JUDGE_DIGEST:
        raise SystemExit("blocked_judge_identity: local Judge tag/digest mismatch")
    if models.get(EMBED_MODEL, {}).get("digest") != EMBED_DIGEST:
        raise SystemExit("blocked_embedding_identity: frozen BGE-M3 digest mismatch")
    version_response = requests.get("http://127.0.0.1:11434/api/version", timeout=10)
    version_response.raise_for_status()
    if version_response.json().get("version") != "0.35.0":
        raise SystemExit("blocked_exact_evaluator_runtime: Ollama version differs from frozen 0.35.0")
    show_response = requests.post("http://127.0.0.1:11434/api/show", json={"model": JUDGE_MODEL, "verbose": False}, timeout=30)
    show_response.raise_for_status()
    show = show_response.json()
    if show.get("details", {}).get("family") != "qwen3":
        raise SystemExit("blocked_judge_identity: expected historical Qwen3-based artifact")

    set_manifest = read_json(MANIFEST_PATH)
    if set_manifest.get("actual_outputs") != 30 or sha256(SET_PATH) != set_manifest.get("set_sha256"):
        raise SystemExit("blocked_calibration_set: fixed 30-output set checksum/size mismatch")
    rows = [json.loads(line) for line in SET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 30 or any(row.get("status") != "answered" for row in rows):
        raise SystemExit("blocked_calibration_set: expected exactly 30 answered rows")

    # Reuse the frozen RAGAS 0.4.3 metric and unmodified native prompt. The
    # selected artifact differs from every currently known candidate digest;
    # its role here is Judge-only and the historical DeepSeek-8B outputs were
    # excluded from the calibration sample.
    from ragas.metrics import Faithfulness
    from ragas.run_config import RunConfig
    from src.evaluation.ragas_eval import runtime
    from src.evaluation.ragas_eval.runner import score_row
    from src.evaluation.ragas_eval.runtime import append_jsonl, make_adapters, sha_text

    runtime.JUDGE_MODEL = JUDGE_MODEL
    runtime.JUDGE_DIGEST = JUDGE_DIGEST
    runtime.OPTIONS = dict(OPTIONS)
    judge, _embeddings = make_adapters(RAW_PATH)
    metric = Faithfulness(llm=judge)
    metric.init(RunConfig(max_retries=1, timeout=1800))
    metrics = {"faithfulness": metric}

    prompt_metadata = {}
    for key, prompt in metric.get_prompts().items():
        prompt_metadata[key] = {
            "instruction": prompt.instruction,
            "examples": len(prompt.examples),
            "output_schema": prompt.output_model.model_json_schema(),
            "prompt_sha256": sha_text(prompt.to_string()),
        }

    run_outputs: dict[int, dict[str, dict]] = {1: {}, 2: {}}
    started = datetime.now(timezone.utc).isoformat()
    for run_number in (1, 2):
        for index, row in enumerate(rows, 1):
            scoring_row = dict(row)
            scoring_row["source_question_id"] = row["question_id"]
            scoring_row["question_id"] = row["calibration_id"]
            judge.identity = {"calibration_id": row["calibration_id"], "condition": row["condition"], "metric": "faithfulness", "pass_number": run_number}
            result = score_row(scoring_row, judge, metrics, stage=f"phase20_1_pass_{run_number}")
            score = result["metrics"]["faithfulness"]
            summary = {
                "calibration_id": row["calibration_id"],
                "question_id": row["question_id"],
                "condition": row["condition"],
                "pass_number": run_number,
                "status": score.get("status"),
                "score": score.get("score"),
                "parse_status": score.get("parse_status"),
                "failure_reason": score.get("failure_reason"),
                "attempt_count": score.get("attempt_count", 0),
                "retry_count": score.get("retry_count", 0),
            }
            run_outputs[run_number][row["calibration_id"]] = summary
            append_jsonl(SCORE_PATH, summary)
            print(f"Judge calibration pass {run_number}: {index}/30 {row['calibration_id']} {summary['status']}", flush=True)

    scores_by_metric = []
    for metric_name in ("faithfulness",):
        paired = []
        for row in rows:
            left = run_outputs[1][row["calibration_id"]].get("score")
            right = run_outputs[2][row["calibration_id"]].get("score")
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                paired.append((float(left), float(right)))
        first = [a for a, _ in paired]
        second = [b for _, b in paired]
        deltas = [b - a for a, b in paired]
        scores_by_metric.append({
            "metric": metric_name,
            "n_pairs": len(paired),
            "exact_agreement_count": sum(a == b for a, b in paired),
            "exact_agreement": sum(a == b for a, b in paired) / len(paired) if paired else None,
            "mean_absolute_difference": statistics.mean(abs(x) for x in deltas) if deltas else None,
            "pearson": correlation(first, second),
            "spearman": correlation(rankdata(first), rankdata(second)) if first else None,
            "score_difference_mean_pass2_minus_pass1": statistics.mean(deltas) if deltas else None,
        })

    raw_records = [json.loads(line) for line in RAW_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    attempt_count = len(raw_records)
    schema_failures = sum(not row.get("schema_status") for row in raw_records)
    truncations = sum(row.get("finish_reason") == "length" or "technical_completion_failure:length" in str(row.get("failure_reason")) for row in raw_records)
    technical_failures = sum(not row.get("schema_status") or not row.get("json_parse_status") or row.get("finish_reason") != "stop" for row in raw_records)
    valid_first = sum(row.get("status") == "valid" for row in run_outputs[1].values())
    valid_second = sum(row.get("status") == "valid" for row in run_outputs[2].values())
    metrics_parseable = valid_first == 30 and valid_second == 30
    schema_parse_rate = (attempt_count - schema_failures) / attempt_count if attempt_count else 0.0
    current_candidate_digests = [
        "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f",
        "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364",
        "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b",
    ]
    no_conflict = JUDGE_DIGEST not in current_candidate_digests and show.get("details", {}).get("family") == "qwen3"
    ready = (
        no_conflict and valid_first == 30 and valid_second == 30
        and schema_parse_rate == 1.0 and truncations == 0
        and technical_failures == 0 and metrics_parseable
    )

    execution = {
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "judge_model": JUDGE_MODEL,
        "judge_digest": JUDGE_DIGEST,
        "runtime": "Ollama 0.35.0",
        "ragas_version": importlib.metadata.version("ragas"),
        "generation_parameters": OPTIONS,
        "calibration_set_sha256": set_manifest["set_sha256"],
        "calibration_outputs": 30,
        "completed_pass1": valid_first,
        "completed_pass2": valid_second,
        "raw_judge_attempt_count": attempt_count,
        "schema_parse_rate_all_attempts": schema_parse_rate,
        "schema_failure_attempt_count": schema_failures,
        "truncation_count_all_attempts": truncations,
        "technical_failure_count_all_attempts": technical_failures,
        "metrics_parseable": metrics_parseable,
        "metric_prompt_metadata": prompt_metadata,
        "independent_judge_ready": ready,
    }
    repeatability = {
        "status": "completed" if metrics_parseable else "incomplete",
        "outputs_per_pass": 30,
        "passes": 2,
        "completed_pairs": len([x for x in run_outputs[1].values() if x.get("status") == "valid" and run_outputs[2][x["calibration_id"]].get("status") == "valid"]),
        "metrics": scores_by_metric,
        "human_validity_claim": False,
    }
    write_json(OUT / "judge_calibration_execution.json", execution)
    write_json(OUT / "judge_repeatability.json", repeatability)
    preflight = read_json(OUT / "judge_preflight.json")
    preflight.update({
        "status": "ready" if ready else "blocked_evaluator_runtime",
        "independent_judge_ready": ready,
        "first_pass_completed": valid_first,
        "second_pass_completed": valid_second,
        "schema_parse_rate": schema_parse_rate,
        "truncation_count": truncations,
        "technical_failure_count": technical_failures,
        "metrics_parseable": metrics_parseable,
        "raw_attempt_count": attempt_count,
        "reason": "Calibration criteria passed." if ready else "Calibration failed one or more zero-failure gates; see judge_calibration_execution.json and raw traces.",
    })
    write_json(OUT / "judge_preflight.json", preflight)
    judge_manifest = read_json(OUT / "judge_manifest.json")
    judge_manifest.update({
        "independent_judge_ready": ready,
        "generation_parameters": OPTIONS,
        "structured_output_mode": "Ollama native JSON Schema; unchanged RAGAS 0.4.3 Faithfulness prompts",
        "calibration_set_sha256": set_manifest["set_sha256"],
        "calibration_execution_sha256": sha256(OUT / "judge_calibration_execution.json"),
        "known_limitation": "The Judge artifact was a historical Phase 17 generator, although it is a different content-addressed artifact from the planned current candidates. Its outputs are used only for Judge calibration; it is never a candidate in Phase 20.",
    })
    write_json(OUT / "judge_manifest.json", judge_manifest)
    readiness = read_json(OUT / "readiness.json")
    gates = readiness["gates"]
    gates["judge_ready"] = ready
    from src.evaluation.phase20_1_protocol import phase20_2_readiness
    readiness.update(phase20_2_readiness(gates))
    readiness.update({
        "gates": gates,
        "four_models_ready": gates["model_identity_ready"],
        "independent_judge_ready": ready,
        "evidence_matrix_ready": gates["evidence_matrix_ready"],
        "high_risk_ready": gates["high_risk_ready"],
        "calculation_ready": gates["calculation_ready"],
        "formal_candidate_ranking": False,
        "winner": None,
        "phase20_1_stops_at_readiness": True,
    })
    write_json(OUT / "readiness.json", readiness)
    print(json.dumps({"independent_judge_ready": ready, "pass1": valid_first, "pass2": valid_second,
                      "schema_parse_rate": schema_parse_rate, "truncations": truncations,
                      "technical_failures": technical_failures, "repeatability": scores_by_metric}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
