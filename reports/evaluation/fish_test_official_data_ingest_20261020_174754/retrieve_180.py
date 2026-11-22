from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
AA = ROOT / "reports/evaluation/fish_test_phase_aa_20261019_220906"
DB = ROOT / "research_staging/official_downloads/phase_ab_recovery_20261020_172529/official_open_data_research_index_v2.sqlite3"
QUESTIONS = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


spec = importlib.util.spec_from_file_location("official_data_runtime", AA / "phase_aa_runtime.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load isolated validated retrieval runtime")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)
runtime.DB_PATH = DB

questions = read_jsonl(QUESTIONS)
results = []
for i, q in enumerate(questions, 1):
    result = runtime.retrieve(q["question_text"], q["species_chinese"], top_k=5)
    result["corpus_id"] = "official_open_data_research_index_v2"
    result["formal_corpus_admission"] = False
    result["question_id"] = q["question_id"]
    result["category"] = q.get("inferred_category")
    result["query_text_source"] = "question_text only; no candidate reference answer or rubric included"
    results.append(result)
    if i % 10 == 0:
        print(f"retrieved {i}/{len(questions)}", flush=True)

out_path = OUT / "retrieval_results_180.jsonl"
out_path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in results), encoding="utf-8")

by_species = {}
for sp_name in sorted({q["species_chinese"] for q in questions}):
    subset = [r for r in results if r["target_species"] == sp_name]
    by_species[sp_name] = {"questions": len(subset), "at_least_one_context": sum(bool(r["reranked_top"]) for r in subset), "full_top5": sum(len(r["reranked_top"]) == 5 for r in subset), "context_count_distribution": dict(Counter(str(len(r["reranked_top"])) for r in subset))}

all_top = [c for r in results for c in r["reranked_top"]]
summary = {
    "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    "questions": len(results),
    "at_least_one_context": sum(bool(r["reranked_top"]) for r in results),
    "full_top5": sum(len(r["reranked_top"]) == 5 for r in results),
    "returned_context_count": len(all_top),
    "context_count_distribution": dict(Counter(str(len(r["reranked_top"])) for r in results)),
    "species": by_species,
    "retrieval_method": {"runtime_source": str(AA / "phase_aa_runtime.py"), "database": str(DB), "database_sha256": results[0]["database_sha256"] if results else None, "bm25_dense_rrf_reranker": "BM25 character bigrams + BGE-M3 dense; RRF k=60; BGE Reranker v2-m3; top 5", "query_text_only": True, "post_retrieval_species_scope_gate": True, "corpus_formal_admission": False},
    "benchmark_evidence_status": "Retrieval candidates only. A hit does not constitute answer support or a relevance gold label.",
    "human_gold": 0,
}
(OUT / "retrieval_coverage_180.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"questions":len(results),"at_least_one_context":summary["at_least_one_context"],"full_top5":summary["full_top5"],"returned_context_count":len(all_top)},ensure_ascii=False))
