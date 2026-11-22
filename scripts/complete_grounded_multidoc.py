"""Retry only evidence-grounded multi-document Silver generation and refresh v1 reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_grounded_silver import (  # noqa: E402
    build_multi,
    call_with_retry,
    file_sha256,
    read_jsonl,
    write_json,
    write_jsonl,
)
from src.evaluation.grounded.generator import GENERATION_CONFIG, generate_multidocument  # noqa: E402
from src.evaluation.grounded.pipeline import (  # noqa: E402
    benchmark_readiness,
    build_evidence_pool,
    distribution_report,
    duplicate_analysis,
    quality_report,
    select_multidocument_pairs,
)


def main() -> int:
    corpus_path = ROOT / "data/evaluation/corpus_v2.jsonl"
    pool_path = ROOT / "data/evaluation/grounded/evidence_pool_v1.jsonl"
    questions_path = ROOT / "data/evaluation/grounded/questions_v1.jsonl"
    reports = ROOT / "reports/evaluation/grounded"
    model = "gemma2:9b"
    corpus_sha = file_sha256(corpus_path)
    corpus_rows = read_jsonl(corpus_path)
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus_rows}
    pool = read_jsonl(pool_path)
    accepted = [row for row in pool if row.get("evidence_quality_status") == "accepted"]
    pairs = select_multidocument_pairs(accepted, 6)
    old_questions = read_jsonl(questions_path)
    old_quality = json.loads((reports / "quality_v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((reports / "manifest_v1.json").read_text(encoding="utf-8"))

    generated: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []
    recovered: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    request_failures = 0
    config = {**GENERATION_CONFIG, "model": model, "endpoint": "http://127.0.0.1:11434/api/chat",
              "evidence_only_system_instruction": True, "multidocument_retry_prompt": "verbatim_supporting_quotes_v2"}

    for index, pair in enumerate(pairs, 1):
        raw, error = call_with_retry(generate_multidocument, model, pair[0], pair[1])
        if error:
            request_failures += 1
            audit.append({"pair": [row["chunk_id"] for row in pair], "status": "request_failed", "error": error})
            continue
        items = raw.get("items") or []
        before = len(recovered)
        recovered.extend(build_multi(pair, raw, model, config, corpus_sha, corpus_by_id, generated, validation_errors))
        audit.append({
            "pair": [row["chunk_id"] for row in pair],
            "species": pair[0].get("species"),
            "category": pair[0].get("category"),
            "generated_items": len(items),
            "accepted_items": len(recovered) - before,
            "status": "completed",
        })
        print(f"multi pair {index}/{len(pairs)}: accepted {len(recovered) - before}", flush=True)

    # Replace prior multi-document drafts with the stricter, label-free regeneration.
    retained = [row for row in old_questions if not row.get("multi_document")]
    combined = retained + recovered
    duplicates = duplicate_analysis(combined)
    duplicate_ids = {row["question_id"] for row in duplicates["exact_duplicates"]}
    final_questions = sorted((row for row in combined if row["question_id"] not in duplicate_ids),
                             key=lambda row: row["question_id"])
    duplicate_report = duplicate_analysis(final_questions)
    write_jsonl(questions_path, final_questions)

    coverage = distribution_report(final_questions, pool, corpus_sha)
    old_validation_failures = int(old_quality.get("evidence_validation_failure_count", 0))
    old_errors = [{"question_id": f"prior-multi-retry-{idx}", "errors": ["supporting_quote_not_in_evidence"]}
                  for idx in range(old_validation_failures)]
    quality = quality_report(
        final_questions,
        [{}] * int(old_quality.get("generation_success", 0)) + generated,
        old_errors + validation_errors,
        duplicate_report,
        pool,
        int(old_quality.get("generation_request_failures", 0)) + request_failures,
    )
    readiness = benchmark_readiness(final_questions, corpus_by_id, corpus_sha)
    manifest.update({
        "question_dataset_sha256": file_sha256(questions_path),
        "multidocument_prompt_revision": "verbatim_supporting_quotes_v2",
        "retrieval_benchmark_executed": False,
    })
    write_json(reports / "coverage_v1.json", coverage)
    write_json(reports / "quality_v1.json", quality)
    write_json(reports / "readiness_v1.json", readiness)
    write_json(reports / "manifest_v1.json", manifest)
    write_json(reports / "multidocument_retry_v1.json", {
        "model": model,
        "pairs_attempted": len(pairs),
        "questions_accepted": len(recovered),
        "request_failures": request_failures,
        "pair_results": audit,
        "readiness": readiness["grounded_silver_ready"],
    })
    print(json.dumps({
        "questions": len(final_questions),
        "multi_document": sum(bool(row.get("multi_document")) for row in final_questions),
        "readiness": readiness["grounded_silver_ready"],
    }, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

