"""Build the Phase 11 evidence-first Silver benchmark without touching production RAG."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.grounded.generator import (  # noqa: E402
    GENERATION_CONFIG,
    GenerationError,
    generate_calculation_questions,
    generate_multidocument,
    generate_single_evidence,
)
from src.evaluation.grounded.pipeline import (  # noqa: E402
    ALLOWED_QUERY_STYLES,
    benchmark_readiness,
    build_calculation_answer,
    build_evidence_pool,
    distribution_report,
    duplicate_analysis,
    extract_simple_feed_rate,
    make_question_record,
    quality_report,
    select_multidocument_pairs,
    select_single_evidence,
    validate_grounded_question,
)

CORPUS_PATH = ROOT / "data/evaluation/corpus_v2.jsonl"
POOL_PATH = ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"
QUESTIONS_PATH = ROOT / "data/evaluation/grounded/questions_v1.jsonl"
REPORT_DIR = ROOT / "reports/evaluation/grounded"
CHECKPOINT_PATH = REPORT_DIR / "generation_checkpoint.jsonl"
MODEL_DEFAULT = "gemma2:9b"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


def make_question_id(style: str, evidence_ids: list[str], text: str) -> str:
    key = "\x1f".join(["grounded-v1", style, *sorted(evidence_ids), text.strip()])
    return "grounded_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def parse_styles(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = raw.get("items")
    if not isinstance(values, list):
        raise GenerationError("response does not contain items array")
    return {str(item["query_style"]): item for item in values
            if isinstance(item, dict) and item.get("query_style") in ALLOWED_QUERY_STYLES}


def read_checkpoint() -> dict[str, dict[str, Any]]:
    if not CHECKPOINT_PATH.exists():
        return {}
    return {row["task_id"]: row for row in read_jsonl(CHECKPOINT_PATH)}


def save_checkpoint(rows: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    rows[row["task_id"]] = row
    write_jsonl(CHECKPOINT_PATH, list(rows.values()))


def call_with_retry(function, *args) -> tuple[dict[str, Any] | None, str | None]:
    error = None
    for _ in range(2):
        try:
            return function(*args), None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    return None, error


def build_single(evidence: dict[str, Any], raw: dict[str, Any], model: str, config: dict[str, Any],
                 corpus_sha: str, corpus_by_id: dict[str, dict[str, Any]],
                 generated: list[dict[str, Any]], validation_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = []
    for style, item in parse_styles(raw).items():
        question_text = str(item.get("question") or "").strip()
        record = make_question_record(
            question_id=make_question_id(style, [evidence["chunk_id"]], question_text),
            question=question_text, answer=str(item.get("reference_answer") or ""), evidences=[evidence],
            style=style, category=str(evidence["category"]), corpus_sha256=corpus_sha,
            generation_model=model, generation_config=config,
            supporting_quotes=[{"chunk_id": evidence["chunk_id"],
                                "quote": str(item.get("supporting_quote") or "").strip()}],
        )
        generated.append(record)
        errors = validate_grounded_question(record, corpus_by_id)
        if errors:
            validation_errors.append({"question_id": record["question_id"], "errors": errors})
        else:
            accepted.append(record)
    return accepted


def build_multi(pair: list[dict[str, Any]], raw: dict[str, Any], model: str, config: dict[str, Any],
                corpus_sha: str, corpus_by_id: dict[str, dict[str, Any]],
                generated: list[dict[str, Any]], validation_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = []
    items = parse_styles(raw)
    for style in ALLOWED_QUERY_STYLES:
        item = items.get(style)
        if not item:
            continue
        raw_quotes = item.get("supporting_quotes") or []
        quotes = []
        for marker, evidence in zip(("A", "B"), pair):
            quote = next((row.get("quote") for row in raw_quotes
                          if isinstance(row, dict) and row.get("evidence") == marker), "")
            quotes.append({"chunk_id": evidence["chunk_id"], "quote": str(quote or "").strip()})
        question_text = str(item.get("question") or "").strip()
        record = make_question_record(
            question_id=make_question_id(style, [row["chunk_id"] for row in pair], question_text),
            question=question_text, answer=str(item.get("reference_answer") or ""), evidences=pair,
            style=style, category=str(pair[0]["category"]), corpus_sha256=corpus_sha,
            generation_model=model, generation_config=config, supporting_quotes=quotes,
        )
        generated.append(record)
        errors = validate_grounded_question(record, corpus_by_id)
        if not errors:
            answer_compact = "".join(char for char in record["reference_answer"]
                                     if char.isalnum() or "\u3400" <= char <= "\u9fff")
            for quote in quotes:
                quote_compact = "".join(char for char in quote["quote"]
                                        if char.isalnum() or "\u3400" <= char <= "\u9fff")
                shared = sum(1 for index in range(max(0, len(quote_compact) - 1))
                             if quote_compact[index:index + 2] in answer_compact)
                if len(quote_compact) < 8 or shared / max(1, len(quote_compact) - 1) < 0.12:
                    errors.append("multi_document_evidence_not_reflected_in_answer")
        if errors:
            validation_errors.append({"question_id": record["question_id"], "errors": sorted(set(errors))})
        else:
            accepted.append(record)
    return accepted


def build_calculations(evidence: dict[str, Any], formula: tuple[float, float, str],
                       raw: dict[str, Any], model: str, config: dict[str, Any], corpus_sha: str,
                       corpus_by_id: dict[str, dict[str, Any]], generated: list[dict[str, Any]],
                       validation_errors: list[dict[str, Any]], biomass_values: list[int]) -> list[dict[str, Any]]:
    low, high, formula_quote = formula
    rows = raw.get("items") or []
    by_value = {int(row["biomass_kg"]): row for row in rows
                if isinstance(row, dict) and str(row.get("biomass_kg", "")).isdigit()}
    accepted = []
    for biomass in biomass_values:
        item = by_value.get(biomass)
        if not item or item.get("query_style") not in ALLOWED_QUERY_STYLES:
            continue
        style = str(item["query_style"])
        calculation = build_calculation_answer(biomass, low, high)
        calculation_spec = {
            **calculation, "rate_percent": [low, high], "input": {"biomass_kg": biomass},
            "result_kg": calculation["result_kg"], "formula_text": formula_quote,
        }
        question_text = str(item.get("question") or "").strip()
        record = make_question_record(
            question_id=make_question_id(style, [evidence["chunk_id"]], question_text),
            question=question_text, answer=calculation["reference_answer"], evidences=[evidence],
            style=style, category="calculation", corpus_sha256=corpus_sha,
            generation_model=model, generation_config=config,
            supporting_quotes=[{"chunk_id": evidence["chunk_id"], "quote": formula_quote}],
            calculation_spec=calculation_spec, reference_answer_source="deterministic_calculation",
        )
        generated.append(record)
        errors = validate_grounded_question(record, corpus_by_id)
        if errors:
            validation_errors.append({"question_id": record["question_id"], "errors": errors})
        else:
            accepted.append(record)
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL_DEFAULT, help="Installed local Ollama model; default: gemma2:9b")
    parser.add_argument("--target", type=int, default=180)
    args = parser.parse_args()
    if not CORPUS_PATH.exists():
        raise SystemExit(f"Evaluation Corpus v2 not found: {CORPUS_PATH}")
    if POOL_PATH.exists() or QUESTIONS_PATH.exists():
        raise SystemExit("Grounded Silver v1 output already exists; refusing to overwrite a versioned artifact.")

    corpus_sha = file_sha256(CORPUS_PATH)
    corpus_rows = read_jsonl(CORPUS_PATH)
    corpus_by_id = {str(row.get("chunk_id")): row for row in corpus_rows if row.get("chunk_id")}
    pool = build_evidence_pool(corpus_rows)
    write_jsonl(POOL_PATH, pool)
    accepted_evidence = [row for row in pool if row.get("evidence_quality_status") == "accepted"]
    pairs = select_multidocument_pairs(accepted_evidence, 6)
    paired_ids = {row["chunk_id"] for pair in pairs for row in pair}

    formula_candidates = []
    for evidence in accepted_evidence:
        formula = extract_simple_feed_rate(evidence)
        if formula and evidence.get("species"):
            formula_candidates.append((evidence, formula))
    formula_candidates.sort(key=lambda pair: pair[0]["chunk_id"])
    calculation_plan = formula_candidates[:1]
    calculation_count = 3 * len(calculation_plan)
    single_count = max(0, (args.target - 3 * len(pairs) - calculation_count) // 3)
    single_evidence = select_single_evidence(accepted_evidence, single_count, paired_ids, max_per_document=7)

    import requests
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
    tags.raise_for_status()
    model_names = {str(row.get("name")) for row in tags.json().get("models", [])}
    if args.model not in model_names:
        raise SystemExit(f"Requested local model is not installed: {args.model}")

    config = dict(GENERATION_CONFIG)
    config.update({
        "model": args.model, "endpoint": "http://127.0.0.1:11434/api/chat",
        "evidence_only_system_instruction": True, "calculation_answers_deterministic": True,
    })
    checkpoint = read_checkpoint()
    generated: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []
    accepted_questions: list[dict[str, Any]] = []
    request_failures = 0
    tasks: list[tuple[str, str, Any]] = []
    tasks.extend(("single", row["chunk_id"], row) for row in single_evidence)
    tasks.extend(("multi", "|".join(row["chunk_id"] for row in pair), pair) for pair in pairs)
    tasks.extend(("calculation", evidence["chunk_id"], (evidence, formula))
                 for evidence, formula in calculation_plan)

    for index, (kind, task_key, payload) in enumerate(tasks, 1):
        task_id = f"{args.model}:{corpus_sha[:12]}:{kind}:{task_key}"
        saved = checkpoint.get(task_id)
        if saved and saved.get("status") == "success":
            raw = saved["response"]
        else:
            if kind == "single":
                function, call_args = generate_single_evidence, (args.model, payload)
            elif kind == "multi":
                function, call_args = generate_multidocument, (args.model, payload[0], payload[1])
            else:
                evidence, formula = payload
                low, high, _quote = formula
                function, call_args = generate_calculation_questions, (
                    args.model, evidence, low, high, [100, 250, 500])
            raw, error = call_with_retry(function, *call_args)
            if error:
                request_failures += 1
                save_checkpoint(checkpoint, {"task_id": task_id, "kind": kind, "status": "failed", "error": error})
                print(f"{index}/{len(tasks)} {kind} failed: {error}", flush=True)
                continue
            save_checkpoint(checkpoint, {"task_id": task_id, "kind": kind, "status": "success", "response": raw})

        if kind == "single":
            produced = build_single(payload, raw, args.model, config, corpus_sha, corpus_by_id,
                                    generated, validation_errors)
        elif kind == "multi":
            produced = build_multi(payload, raw, args.model, config, corpus_sha, corpus_by_id,
                                    generated, validation_errors)
        else:
            evidence, formula = payload
            produced = build_calculations(evidence, formula, raw, args.model, config, corpus_sha,
                                          corpus_by_id, generated, validation_errors, [100, 250, 500])
        accepted_questions.extend(produced)
        print(f"{index}/{len(tasks)} {kind}: accepted {len(produced)}; total {len(accepted_questions)}", flush=True)

    initial_duplicate_report = duplicate_analysis(accepted_questions)
    duplicate_ids = {row["question_id"] for row in initial_duplicate_report["exact_duplicates"]}
    final_questions = [row for row in accepted_questions if row["question_id"] not in duplicate_ids]
    final_questions.sort(key=lambda row: row["question_id"])
    final_duplicate_report = duplicate_analysis(final_questions)
    duplicate_report = {
        "exact_duplicates": initial_duplicate_report["exact_duplicates"],
        "near_duplicate_candidates": final_duplicate_report["near_duplicate_candidates"],
    }
    write_jsonl(QUESTIONS_PATH, final_questions)

    coverage = distribution_report(final_questions, pool, corpus_sha)
    quality = quality_report(final_questions, generated, validation_errors, duplicate_report, pool, request_failures)
    readiness = benchmark_readiness(final_questions, corpus_by_id, corpus_sha)
    manifest = {
        "dataset_version": "corpus-grounded-silver-v1",
        "benchmark_type": "silver",
        "generation_source": "corpus_grounded_ai",
        "evidence_pool_sha256": file_sha256(POOL_PATH),
        "evaluation_corpus_sha256": corpus_sha,
        "question_dataset_sha256": file_sha256(QUESTIONS_PATH),
        "generation_model": args.model,
        "generation_config": config,
        "retrieval_benchmark_executed": False,
    }
    write_json(REPORT_DIR / "coverage_v1.json", coverage)
    write_json(REPORT_DIR / "quality_v1.json", quality)
    write_json(REPORT_DIR / "readiness_v1.json", readiness)
    write_json(REPORT_DIR / "manifest_v1.json", manifest)
    print(json.dumps({
        "questions": len(final_questions),
        "accepted_evidence": len(accepted_evidence),
        "pool": len(pool),
        "request_failures": request_failures,
        "readiness": readiness["grounded_silver_ready"],
    }, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
