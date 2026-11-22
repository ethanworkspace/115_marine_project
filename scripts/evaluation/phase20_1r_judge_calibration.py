"""Run the fixed 30-output, two-pass Phase 20.1R Judge calibration.

No candidate answer generation, ranking, or winner selection is performed.
Each pass is a fresh single request per frozen calibration output; there is no
retry or score-based selection.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1R"
SET_PATH = ROOT / "reports/evaluation/final_model_selection/phase20_1/judge_calibration_set.jsonl"
SET_MANIFEST = ROOT / "reports/evaluation/final_model_selection/phase20_1/judge_calibration_manifest.json"
MODEL = "mistral-nemo:12b-instruct-2407-q4_K_M"
DIGEST = "daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55"
OPTIONS = {"temperature": 0, "top_p": 1, "seed": 20021, "num_predict": 512, "num_ctx": 16384}
SCHEMA_PATH = ROOT / "schemas/evaluation_judge_output_v1.schema.json"
PROMPT_PATH = ROOT / "prompts/evaluation_judge_v1.txt"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    dx = math.sqrt(sum((v - mx) ** 2 for v in x))
    dy = math.sqrt(sum((v - my) ** 2 for v in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (dx * dy) if dx and dy else None


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    pos = 0
    while pos < len(order):
        end = pos + 1
        while end < len(order) and values[order[end]] == values[order[pos]]:
            end += 1
        rank = (pos + 1 + end) / 2
        for i in order[pos:end]:
            out[i] = rank
        pos = end
    return out


def valid_scores(value: object) -> bool:
    keys = {"faithfulness", "answer_relevancy", "silver_reference_correctness"}
    return (
        isinstance(value, dict)
        and set(value) == keys
        and all(isinstance(value[k], (int, float)) and not isinstance(value[k], bool) and math.isfinite(value[k]) and 0 <= value[k] <= 1 for k in keys)
    )


def make_user_input(row: dict) -> str:
    contexts = row.get("contexts", [])
    formatted = "\n\n".join(f"Evidence {i + 1}:\n{context}" for i, context in enumerate(contexts))
    return (
        "Question:\n" + row["question"] + "\n\nAnswer:\n" + row["answer"]
        + "\n\nEvidence contexts:\n" + formatted
        + "\n\nAI-generated Silver reference (comparison reference only):\n" + row["reference_answer"]
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / "judge_calibration.jsonl"
    if raw_path.exists():
        raise SystemExit(f"Refusing to overwrite {raw_path}")
    set_bytes = SET_PATH.read_bytes()
    set_manifest = json.loads(SET_MANIFEST.read_text(encoding="utf-8"))
    if sha(set_bytes) != set_manifest["set_sha256"] or set_manifest.get("actual_outputs") != 30:
        raise SystemExit("Fixed 30-output calibration set checksum/size mismatch")
    rows = [json.loads(line) for line in set_bytes.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 30 or any(r.get("status") != "answered" for r in rows):
        raise SystemExit("Calibration set must contain exactly 30 frozen answered outputs")
    tag_rows = requests.get("http://127.0.0.1:11434/api/tags", timeout=20).json().get("models", [])
    model = next((r for r in tag_rows if r.get("name") == MODEL), None)
    if not model or model.get("digest") != DIGEST:
        raise SystemExit("Dedicated Judge tag/digest mismatch")
    show = requests.post("http://127.0.0.1:11434/api/show", json={"model": MODEL, "verbose": False}, timeout=60).json()
    api_version = requests.get("http://127.0.0.1:11434/api/version", timeout=10).json().get("version")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    manifest = {
        "judge_name": "Mistral NeMo Instruct 12B 2407",
        "runtime_name": MODEL,
        "artifact_digest": DIGEST,
        "artifact_size_bytes": model.get("size"),
        "architecture": show.get("details", {}).get("family"),
        "parameter_count": show.get("model_info", {}).get("general.parameter_count", 12247782400),
        "quantization": show.get("details", {}).get("quantization_level"),
        "context_length_native": show.get("model_info", {}).get("llama.context_length"),
        "context_length_experimental": OPTIONS["num_ctx"],
        "license": show.get("model_info", {}).get("general.license", "apache-2.0"),
        "artifact_source": "Ollama library mistral-nemo:12b-instruct-2407-q4_K_M; upstream Mistral-Nemo-Instruct-2407",
        "runtime": "Ollama",
        "runtime_version": api_version,
        "role": "evaluation-only independent Judge; not a Generator candidate",
        "parameters": OPTIONS,
        "structured_output_mode": "Ollama /api/chat JSON Schema format",
        "schema_path": "schemas/evaluation_judge_output_v1.schema.json",
        "schema_sha256": sha(SCHEMA_PATH.read_bytes()),
        "prompt_path": "prompts/evaluation_judge_v1.txt",
        "prompt_sha256": sha(PROMPT_PATH.read_bytes()),
        "calibration_set_sha256": sha(set_bytes),
        "sampling_rule": set_manifest.get("sampling_rule"),
        "requires_chain_of_thought": False,
        "requires_private_reasoning": False,
        "judge_identity_frozen_before_calibration": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "judge_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "judge_protocol.json").write_text(json.dumps({
        "protocol_id": "judge_protocol_v1",
        "metric_fields": ["faithfulness", "answer_relevancy", "silver_reference_correctness"],
        "same_system_prompt_schema_context_format_parameters_for_every_row": True,
        "input_fields": ["question", "answer", "contexts", "reference_answer"],
        "generator_identity_shown": False,
        "max_fresh_passes": 2,
        "technical_retry": "none; all failures are retained and readiness fails",
        "temperature": 0,
        "top_p": 1,
        "seed": 20021,
        "num_predict": 512,
        "num_ctx": 16384,
        "judge_prompt_sha256": manifest["prompt_sha256"],
        "schema_sha256": manifest["schema_sha256"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    score_rows: dict[int, dict[str, dict]] = {1: {}, 2: {}}
    technical_failures = truncations = schema_failures = 0
    with raw_path.open("x", encoding="utf-8") as output:
        for pass_number in (1, 2):
            for row in rows:
                payload = {
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": make_user_input(row)},
                    ],
                    "format": schema,
                    "stream": False,
                    "options": OPTIONS,
                }
                started = time.perf_counter()
                error = None
                response_body: dict = {}
                try:
                    response = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=1800)
                    response.raise_for_status()
                    response_body = response.json()
                    raw = response_body.get("message", {}).get("content", "")
                except Exception as exc:  # recorded as a technical failure; no retry
                    raw = ""
                    error = f"{type(exc).__name__}: {exc}"
                    technical_failures += 1
                latency = time.perf_counter() - started
                done_reason = response_body.get("done_reason")
                if done_reason == "length":
                    truncations += 1
                parse_error = None
                parsed = None
                try:
                    parsed = json.loads(raw)
                except Exception as exc:
                    parse_error = f"{type(exc).__name__}: {exc}"
                schema_valid = valid_scores(parsed)
                if not schema_valid:
                    schema_failures += 1
                record = {
                    "calibration_id": row["calibration_id"],
                    "pass_number": pass_number,
                    "attempt_number": 1,
                    "raw_output": raw,
                    "raw_output_sha256": sha(raw.encode("utf-8")),
                    "raw_output_preserved": True,
                    "parse_error": parse_error,
                    "schema_valid": schema_valid,
                    "technical_error": error,
                    "done_reason": done_reason,
                    "prompt_eval_count": response_body.get("prompt_eval_count"),
                    "eval_count": response_body.get("eval_count"),
                    "total_duration_ns": response_body.get("total_duration"),
                    "generation_latency_seconds": latency,
                    "scores": parsed if schema_valid else None,
                    "question_id_withheld_from_request": True,
                    "generator_identity_withheld_from_request": True,
                }
                output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()
                if schema_valid:
                    score_rows[pass_number][row["calibration_id"]] = parsed

    metrics = ("faithfulness", "answer_relevancy", "silver_reference_correctness")
    repeatability = {}
    for metric_name in metrics:
        pairs = [(score_rows[1][r["calibration_id"]][metric_name], score_rows[2][r["calibration_id"]][metric_name]) for r in rows if r["calibration_id"] in score_rows[1] and r["calibration_id"] in score_rows[2]]
        first = [float(a) for a, _ in pairs]
        second = [float(b) for _, b in pairs]
        repeatability[metric_name] = {
            "n_paired": len(pairs),
            "exact_agreement_rate": sum(a == b for a, b in pairs) / len(pairs) if pairs else None,
            "mean_absolute_difference": statistics.mean(abs(a-b) for a, b in pairs) if pairs else None,
            "pearson": pearson(first, second),
            "spearman": pearson(ranks(first), ranks(second)) if pairs else None,
            "difference_values_second_minus_first": [b-a for a, b in pairs],
        }
    all_first = all(r["calibration_id"] in score_rows[1] for r in rows)
    all_second = all(r["calibration_id"] in score_rows[2] for r in rows)
    calibration = {
        "calibration_set_id": set_manifest["set_id"],
        "calibration_set_sha256": sha(set_bytes),
        "target_outputs": 30,
        "runs": 2,
        "first_pass_completed": len(score_rows[1]),
        "second_pass_completed": len(score_rows[2]),
        "first_pass_schema_parse_rate": len(score_rows[1]) / 30,
        "second_pass_schema_parse_rate": len(score_rows[2]) / 30,
        "technical_failure_count": technical_failures,
        "schema_failure_count": schema_failures,
        "completion_truncation_count": truncations,
        "raw_output_preservation_rate": 1.0,
        "metrics_parseable": schema_failures == 0,
        "judge_execution_status": "complete" if all_first and all_second and not technical_failures and not truncations and schema_failures == 0 else "blocked_calibration_failure",
        "per_metric_repeatability": repeatability,
        "judge_scores_are_not_human_validation": True,
    }
    (OUT / "judge_calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (OUT / "judge_repeatability.json").write_text(json.dumps(repeatability, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
