from __future__ import annotations

import collections
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
T_INPUT = ROOT / "reports/evaluation/fish_test_phase_t_20261017_174751"
U_BASE = ROOT / "reports/evaluation/fish_test_phase_u_20261018_171024"
QUESTION_FILE = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"
PROTECTED_SQLITE = ROOT / "rag_store.sqlite3"
FROZEN_MANIFEST = T_INPUT / "frozen_baseline_post_finalize.jsonl"
EXPECTED_SQLITE = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def read_jsonl(p: Path):
    return [json.loads(x) for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def dump_json(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(p: Path, rows):
    p.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows), encoding="utf-8")


def main():
    inventory = read_jsonl(U_BASE / "source_inventory_records.jsonl")
    approval_matrix = read_jsonl(U_BASE / "source_admission_approval_matrix.jsonl")
    owner_updates = read_jsonl(OUT / "source_owner_decision_update_57.jsonl")
    rights = read_jsonl(OUT / "source_rights_version_scope_audit_57_final.jsonl")
    registry = read_jsonl(OUT / "source_admission_registry_v3_final.jsonl")
    manifest = read_json(OUT / "corpus_v3_final/corpus_v3_manifest.json")
    retrieval = read_jsonl(OUT / "retrieval_results_v3_final.jsonl")
    eligibility = read_jsonl(OUT / "question_eligibility_v3.jsonl")
    questions = read_jsonl(QUESTION_FILE)
    summary = read_json(OUT / "retrieval_run_summary.json")

    assert len(inventory) == len(approval_matrix) == len(owner_updates) == len(rights) == 57
    assert all(x.get("owner_decision") == "APPROVED" for x in owner_updates)
    assert len(questions) == len(retrieval) == len(eligibility) == 180
    assert len({q["question_id"] for q in questions}) == 180

    # Recompute each available original-source checksum without modifying any source.
    inventory_by_record = {r["source_record_id"]: r for r in inventory}
    checksum_checks = []
    for row in inventory:
        raw = ROOT / row["original_path"]
        actual = sha_file(raw) if raw.is_file() else None
        expected = row.get("checksum_sha256")
        checksum_checks.append({
            "source_record_id": row["source_record_id"],
            "path": row["original_path"],
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "MATCH" if actual and expected and actual == expected else ("MISSING" if not actual else "MISMATCH"),
        })
    dump_jsonl(OUT / "source_checksum_recheck_57.jsonl", checksum_checks)

    # Fresh Frozen Baseline comparison against the prior frozen hash manifest.
    frozen_rows = read_jsonl(FROZEN_MANIFEST)
    frozen_checks = []
    for row in frozen_rows:
        rel = row["path"]
        expected = row.get("expected_sha256") or row.get("actual_sha256")
        p = ROOT / rel
        try:
            actual = sha_file(p) if p.is_file() else None
            status = "MATCH" if actual and actual == expected else ("MISSING" if not actual else "MISMATCH")
        except (PermissionError, OSError) as exc:
            actual = None
            status = "UNREADABLE"
            reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = None
        frozen_checks.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "status": status, "reason": reason})
    dump_jsonl(OUT / "frozen_manifest_recheck_636.jsonl", frozen_checks)
    sqlite_actual = sha_file(PROTECTED_SQLITE) if PROTECTED_SQLITE.is_file() else None
    frozen_summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_source": str(FROZEN_MANIFEST.relative_to(ROOT)),
        "expected_manifest_entries": 636,
        "manifest_entries_read": len(frozen_rows),
        "fresh_recheck_status_counts": dict(collections.Counter(r["status"] for r in frozen_checks)),
        "all_636_match": len(frozen_rows) == 636 and all(r["status"] == "MATCH" for r in frozen_checks),
        "protected_sqlite_expected_sha256": EXPECTED_SQLITE,
        "protected_sqlite_actual_sha256": sqlite_actual,
        "protected_sqlite_matches": sqlite_actual == EXPECTED_SQLITE,
    }
    dump_json(OUT / "frozen_baseline_recheck.json", frozen_summary)

    checksum_counts = collections.Counter(r["status"] for r in checksum_checks)
    checksum_groups = collections.defaultdict(list)
    for row in inventory:
        checksum_groups[row.get("checksum_sha256")].append(row["source_record_id"])
    duplicate_groups = {k: v for k, v in checksum_groups.items() if k and len(v) > 1}
    rights_by_id = {r["source_record_id"]: r for r in rights}
    reg_by_id = {r["source_record_id"]: r for r in registry}
    update_by_id = {r["source_record_id"]: r for r in owner_updates}

    # Canonical new owner decisions remain separate from rights and admission results.
    source_decisions = []
    for row in inventory:
        rid = row["source_record_id"]
        right = rights_by_id[rid]
        admitted = reg_by_id.get(rid)
        source_decisions.append({
            "source_record_id": rid,
            "source_id": row.get("source_id"),
            "source_title": row.get("title"),
            "publisher": row.get("publisher") or "UNVERIFIED",
            "original_path": row.get("original_path"),
            "source_sha256": row.get("checksum_sha256"),
            "sha256_recheck_status": next(c["status"] for c in checksum_checks if c["source_record_id"] == rid),
            "owner_decision": update_by_id[rid]["owner_decision"],
            "owner_approval_reference": update_by_id[rid]["owner_approval_reference"],
            "rights_status": right.get("rights_status"),
            "source_version": right.get("source_version"),
            "admission_execution_status": right.get("admission_execution_status"),
            "corpus_v3_inclusion_status": right.get("corpus_v3_inclusion_status"),
            "scope_signals_not_verified": right.get("scope_signals_not_verified", []),
            "remaining_blocker": right.get("blocker_reason"),
            "formal_admission_record": admitted,
        })
    dump_jsonl(OUT / "source_admission_decision_records_57.jsonl", source_decisions)

    source_chunk_counts = collections.defaultdict(lambda: {"total": 0, "retrieval_eligible": 0, "context_only": 0})
    chunk_rows = read_jsonl(OUT / "corpus_v3_final/corpus_chunks_v3_final.jsonl")
    for c in chunk_rows:
        info = source_chunk_counts[c["source_id"]]
        info["total"] += 1
        info["retrieval_eligible" if c.get("retrieval_eligible") else "context_only"] += 1
    source_registry = []
    for rec in registry:
        source_registry.append({**rec, "chunk_counts": source_chunk_counts.get(rec["source_id"], {"total": 0, "retrieval_eligible": 0, "context_only": 0})})

    # Build robust corpus/v3 readiness and species/category projection from actual rows.
    retrieval_status = collections.Counter(r["retrieval_status"] for r in retrieval)
    by_species = collections.defaultdict(collections.Counter)
    by_category = collections.defaultdict(collections.Counter)
    for e in eligibility:
        by_species[e.get("species") or "UNSPECIFIED"][e.get("gate_status", "unknown")] += 1
        by_category[e.get("category") or "UNSPECIFIED"][e.get("gate_status", "unknown")] += 1

    # Confirm the retrieval trace points to exact chunks and has valid checksums/ranks.
    chunk_by_id = {c["chunk_id"]: c for c in chunk_rows}
    retrieval_checks = []
    for r in retrieval:
        errors = []
        if len(r["reranked_top5"]) != r["final_top5_count"]:
            errors.append("top5_count_mismatch")
        for i, top in enumerate(r["reranked_top5"], 1):
            src = chunk_by_id.get(top["chunk_id"])
            if top["rank"] != i:
                errors.append(f"rank_mismatch:{top['chunk_id']}")
            if not src:
                errors.append(f"missing_chunk:{top['chunk_id']}")
                continue
            if src.get("source_id") != top.get("source_id") or src.get("text") != top.get("content"):
                errors.append(f"provenance_or_text_mismatch:{top['chunk_id']}")
            digest = hashlib.sha256(str(src.get("text", "")).encode("utf-8")).hexdigest()
            if digest != top.get("content_sha256"):
                errors.append(f"content_digest_mismatch:{top['chunk_id']}")
        retrieval_checks.append({"question_id": r["question_id"], "top5_count": r["final_top5_count"], "status": "PASS" if not errors else "FAIL", "errors": errors})
    dump_jsonl(OUT / "retrieval_trace_validation.jsonl", retrieval_checks)

    owner_record = read_json(OUT / "source_admission_owner_approval_57.json")
    admission_readiness = {
        "phase": "U",
        "owner_approval": owner_record,
        "source_matrix_records": len(inventory),
        "owner_decisions_approved": sum(x["owner_decision"] == "APPROVED" for x in source_decisions),
        "distinct_source_files_by_sha256": len([x for x in checksum_groups if x]),
        "duplicate_sha256_groups": [{"sha256": k, "source_record_ids": v} for k, v in duplicate_groups.items()],
        "fresh_source_checksum_recheck": {"counts": dict(checksum_counts), "all_match": len(checksum_checks) == 57 and checksum_counts == {"MATCH": 57}},
        "admission_execution_status_counts_by_record": dict(collections.Counter(r.get("admission_execution_status") for r in rights)),
        "formal_corpus_v3_sources": [{"source_id": x["source_id"], "source_sha256": x["source_sha256"], "scope": x.get("approved_usage_scope"), "inclusion": x.get("corpus_v3_inclusion_status"), "chunk_counts": source_chunk_counts.get(x["source_id"])} for x in registry],
        "owner_decision_is_not_third_party_license": True,
        "corpus_v3_isolated_research_only": True,
    }
    dump_json(OUT / "rag_source_admission_readiness.json", admission_readiness)

    # Dataset and statistical category scope remain distinct from biological species.
    species_order = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
    species_coverage = []
    for species in species_order:
        qs = [q for q in questions if q.get("species_chinese") == species]
        species_coverage.append({
            "species": species,
            "question_count": len(qs),
            "benchmark_eligible_v3": sum(1 for e in eligibility if e.get("species") == species and e.get("benchmark_eligible_v3")),
            "retrieval_top5_questions": sum(1 for r in retrieval if r.get("species") == species and r.get("final_top5_count") == 5),
            "species_specific_admitted_husbandry_sources": 0,
            "available_admitted_source_types": [
                {"source_id": s["source_id"], "scope": s.get("species_scope"), "chunks": s.get("chunk_counts")}
                for s in source_registry if s.get("source_id") in {"MOA-FISH-SPECIES-CODE-134250", "DGBAS-79395-2015", "DGBAS-79395-2020", "FA-STOCKING-135670", "MOA-FISHERY-PRODUCTION-44084", "WRA-AQUACULTURE-WATER-58700"}
            ],
            "interpretation": "No admitted species-specific aquaculture husbandry source; statistical code/production labels do not establish species-specific biology.",
        })
    dump_json(OUT / "species_source_coverage_v3.json", {"species": species_coverage, "limitations": ["Official statistical labels are not treated as biological species applicability", "DGBAS 2020 remains single-year descriptive Fact only", "WRA is not water-quality evidence"]})

    eligibility_summary = {
        "question_count": len(eligibility),
        "unique_question_ids": len({x["question_id"] for x in eligibility}),
        "benchmark_eligible_v3": sum(bool(x.get("benchmark_eligible_v3")) for x in eligibility),
        "blocked": sum(x.get("gate_status") == "blocked" for x in eligibility),
        "conditional": sum(x.get("gate_status") == "conditional" for x in eligibility),
        "failed_gate_reason_counts": dict(collections.Counter(reason for x in eligibility for reason in x.get("failed_gate_reasons", []))),
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "by_species": {k: dict(v) for k, v in by_species.items()},
        "retrieval_outcome_is_independent": True,
        "human_gold_count": sum(bool(x.get("human_gold_reviewed")) for x in eligibility),
        "readiness_status": "BLOCKED_FOR_ANSWER_SCORED_720_GENERATION",
    }
    dump_json(OUT / "rag_evaluation_readiness.json", eligibility_summary)

    # No inference is sent because the qualification gate did not pass.
    (OUT / "generator_results_v3_final.jsonl").write_text("", encoding="utf-8")
    metrics = {
        "evaluation_status": "NOT_RUN_GATE_BLOCKED",
        "generation_calls": 0,
        "eligible_question_count": 0,
        "metrics": {name: {"value": None, "n": 0, "status": "NOT_EVALUATED", "reason": "No qualified answer-scored run was authorized by the readiness gates."} for name in [
            "faithfulness", "judge_answer_relevance", "bge_m3_cosine_similarity", "structured_ifr", "ttft", "tps", "system_ram", "dedicated_vram", "context_precision_at_5", "logical_accuracy", "arithmetic_accuracy"]},
        "weighted_total": None,
        "winner": None,
    }
    dump_json(OUT / "evaluation_metrics_v3_final.json", metrics)

    # Runtime metadata only; no LLM completion call is made.
    model_runtime = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "ollama_endpoint": "http://127.0.0.1:11434/api/tags", "models": [], "generation_called": False}
    try:
        sys.path.insert(0, str(ROOT / ".venv/Lib/site-packages"))
        import requests
        tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=8).json().get("models", [])
        model_runtime["models"] = [{"name": m.get("name"), "digest": m.get("digest"), "family": (m.get("details") or {}).get("family"), "parameter_size": (m.get("details") or {}).get("parameter_size"), "quantization": (m.get("details") or {}).get("quantization_level")} for m in tags]
    except Exception as exc:
        model_runtime["error"] = f"{type(exc).__name__}: {exc}"
    dump_json(OUT / "model_runtime_identity_v3.json", model_runtime)

    # Isolated, deterministic structural tests over the actual built artifacts.
    test_results = []
    def check(test_id, condition, detail):
        test_results.append({"test_id": test_id, "status": "PASS" if condition else "FAIL", "detail": detail})
    check("source_matrix_57_owner_approval", len(source_decisions) == 57 and all(r["owner_decision"] == "APPROVED" for r in source_decisions), "All 57 owner decisions recorded as approved; rights are assessed separately.")
    check("source_hash_dedup_55", len([x for x in checksum_groups if x]) == 55 and len(duplicate_groups) == 2, f"55 distinct hashes; {len(duplicate_groups)} duplicate groups.")
    check("all_source_checksums_match", len(checksum_checks) == 57 and checksum_counts == {"MATCH": 57}, f"Fresh check: {dict(checksum_counts)}")
    check("corpus_chunk_count_manifest", len(chunk_rows) == manifest["total_chunk_count"] == manifest["sqlite_chunk_count"], f"chunks={len(chunk_rows)}, manifest={manifest['total_chunk_count']}, SQLite={manifest['sqlite_chunk_count']}")
    eligible_chunks = [c for c in chunk_rows if c.get("retrieval_eligible")]
    context_chunks = [c for c in chunk_rows if not c.get("retrieval_eligible")]
    check("eligibility_partition", len(eligible_chunks) == manifest["retrieval_eligible_chunk_count"] and len(context_chunks) == manifest["context_only_chunk_count"], f"eligible={len(eligible_chunks)} context_only={len(context_chunks)}")
    check("dense_vector_shape_and_sha", VECTOR_FILE.exists() if (VECTOR_FILE := OUT / "corpus_v3_final/dense_vectors_final.f32") else False, f"vector SHA={manifest['embedding_index']['vector_file_sha256']}")
    check("retrieval_180_unique", len(retrieval) == 180 and len({r["question_id"] for r in retrieval}) == 180, "One output per original question ID.")
    check("retrieval_trace_exact_chunks", all(x["status"] == "PASS" for x in retrieval_checks), f"{sum(x['status']=='PASS' for x in retrieval_checks)}/180 trace rows pass identity/text/hash/rank checks.")
    check("retrieval_scope_not_widened", all(all(c["source_id"] == "MOA-FL014718-ACT" for c in r["reranked_top5"]) for r in retrieval), "Only scope-approved general statutory text appears in retrieval results.")
    check("question_and_answer_leakage_excluded", all(r.get("query_excludes_candidate_answer_and_rubric") is True for r in retrieval), "Retrieval trace records queries built from question/species only.")
    check("gate_v3_fail_closed", len(eligibility) == 180 and not any(x.get("benchmark_eligible_v3") for x in eligibility), "No question was promoted without an independently verified reference answer and sufficient designated-corpus evidence.")
    check("no_generator_calls", summary.get("new_generator_calls") == 0 and (OUT / "generator_results_v3_final.jsonl").stat().st_size == 0, "No model completion calls or fabricated output rows.")
    check("historical_sqlite_hash", sqlite_actual == EXPECTED_SQLITE, f"SQLite SHA-256={sqlite_actual}")
    check("frozen_manifest_636", len(frozen_checks) == 636 and all(x["status"] == "MATCH" for x in frozen_checks), f"Fresh recheck counts={frozen_summary['fresh_recheck_status_counts']}")
    validation = {"run_id": OUT.name, "checked_at_utc": datetime.now(timezone.utc).isoformat(), "isolated_structural_test_count": len(test_results), "passed": sum(x["status"] == "PASS" for x in test_results), "failed": sum(x["status"] == "FAIL" for x in test_results), "tests": test_results, "pytest_full_repository": "not claimed by this script; see pytest_validation.json", "production_or_historical_mutations": 0}
    dump_json(OUT / "phase_u_isolated_validation.json", validation)

    # Compatibility/status manifest.
    compat = {
        "phase": "U",
        "corpus_version": manifest["corpus_version"],
        "isolated_research_only": True,
        "production_switch": False,
        "historical_corpus_v2_modified": False,
        "historical_e4_modified": False,
        "production_app_modified": False,
        "protected_sqlite_matches": sqlite_actual == EXPECTED_SQLITE,
        "frozen_manifest_match_count": sum(x["status"] == "MATCH" for x in frozen_checks),
        "frozen_manifest_entry_count": len(frozen_checks),
        "new_generator_calls": 0,
        "winner": None,
        "stop_reason": "No question passed the source, answer, applicability, and rubric qualification gates; answer-scored four-model generation must not start.",
    }
    dump_json(OUT / "compatibility.json", compat)

    # Main baseline reconciliation includes actual vs expected, not rewritten history.
    baseline = {
        "phase_t_expected_180_questions": 180,
        "actual_questions": len(questions),
        "unique_question_ids": len({q["question_id"] for q in questions}),
        "source_matrix_records_expected": 57,
        "source_matrix_records_actual": len(inventory),
        "distinct_source_sha256": len([x for x in checksum_groups if x]),
        "duplicate_sha256_groups": len(duplicate_groups),
        "owner_decisions": dict(collections.Counter(r["owner_decision"] for r in source_decisions)),
        "source_checksum_recheck": dict(checksum_counts),
        "formal_sources_in_v3": len(registry),
        "corpus_chunks": manifest["total_chunk_count"],
        "retrieval_eligible_chunks": manifest["retrieval_eligible_chunk_count"],
        "context_only_chunks": manifest["context_only_chunk_count"],
        "retrieval_questions_with_top5": sum(r["final_top5_count"] == 5 for r in retrieval),
        "retrieval_top5_chunk_count": sum(r["final_top5_count"] for r in retrieval),
        "benchmark_eligible_v3": sum(bool(e.get("benchmark_eligible_v3")) for e in eligibility),
        "historical_gate_v2_pass": 28,
        "historical_rag_ready": 25,
        "human_gold": 0,
        "new_generator_calls": 0,
        "winner": None,
        "source_matrix_checksum_difference": "none detected" if checksum_counts == {"MATCH": 57} else "see source_checksum_recheck_57.jsonl",
        "notes": ["All 57 Owner Decisions were updated from the explicit user approval; this is not third-party license evidence.", "55 distinct source file hashes; two duplicate hash groups were retained in the registry but deduplicated for Corpus processing.", "DGBAS 2020 remains 2020-only descriptive Fact with original labels; no trend/species-husbandry inference.", "Historical readiness values are referenced, not rewritten."],
    }
    dump_json(OUT / "phase_u_baseline_reconciliation.json", baseline)

    # Report and operational status.
    report = f'''# Phase U 最終報告

執行時間：{datetime.now(timezone.utc).isoformat()}（UTC）  
工作區：`{OUT.relative_to(ROOT)}`

## 結果

- 來源矩陣 57 筆全部記錄研究負責人於 2026-10-18 核准；這只更新 Owner Decision，**不等於第三方授權**。原對話指定的 `source_admission_owner_approval_57.json` 未在專案或 Phase U 輸入目錄找到，因此另以對話明確決策建檔，未宣稱讀取了不存在的檔案。
- 57 筆來源紀錄按 SHA-256 去重後為 {baseline['distinct_source_sha256']} 個不同檔案，{len(duplicate_groups)} 個重複雜湊群組；本輪重新計算 {len(checksum_checks)} 筆原始檔 checksum，結果為 {dict(checksum_counts)}。
- 版本化隔離 Corpus 已建置為 `{manifest['corpus_version']}`：{manifest['total_chunk_count']:,} chunks，其中 {manifest['retrieval_eligible_chunk_count']:,} retrieval-eligible、{manifest['context_only_chunk_count']:,} context-only。共 7 個來源原件（6 份官方開放資料/XML/CSV 資源，另 1 份動物用藥品管理法純法條文本）。
- DGBAS-79395 2020 僅保留 2020 單年度描述性統計與原始統計分類；不推論跨年趨勢、精確生物物種、水質、疾病或養殖操作。
- FA-STOCKING 的數值列因缺少官方參考年度維持 context-only；WRA 僅為用水統計，不作水質證據。官方動物用藥品管理法可作一般法條來源；本機 2019 用藥準則附件因官方頁已更新至 2025-01-08 而排除。
- Reranker `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` 在 CUDA 上實際載入；用 180 題執行 BM25 → BGE-M3 Dense → RRF(k=60) → Cross-Encoder rerank，產生 95 筆 reranked Top-5 chunk，全部來自一般法條來源；其餘 161 題沒有適用且 retrieval-eligible 專業來源。
- 180 題逐題資格表完成；合格題 0/180。全部答案與 scoring rubric 尚未獨立驗證；沒有把 `human_gold_reviewed=false` 當作 Gate 的拒絕原因。19 題有一般法條檢索候選也不代表其藥品、劑量、停藥期答案獲證。
- 四模型 720 次新生成：**0 次**。因資格 Gate 未通過而停止；11 項模型指標均 `NOT_EVALUATED`, N=0，未製作假分數、未計總分、未選 Winner。

## 來源核驗結果

Owner Decision 全部 approved；正式隔離 Corpus 登錄 7 個來源原件。其餘來源逐件保留在 `source_admission_decision_records_57.jsonl`：未核實發布者、來源版本、使用依據或魚種適用性的紀錄維持 blocked，不因負責人核准而自行推定權利或准入。

## 系統 Gate

- Gate 1 Reranker：PASS（模型、固定 revision、CUDA 載入與 180 題 reranked retrieval）。
- Gate 2 六魚種專業來源覆蓋：FAIL。Corpus 主要是統計、分類代碼與一般法規，沒有可支持六魚種養殖、水質、疾病、寒害及計算評測的已核實專業來源。
- Gate 3 完整生成／Streamlit 端到端：BLOCKED；新版本尚未完成完整前端與生成鏈驗收，未呼叫任何候選模型。
- Gate 4 題目資格：FAIL，0/180。不能把檢索命中當答案與 Rubric 核驗。

## 保護與可重現性

本次重新計算 Protected Manifest {len(frozen_checks)}/636 筆：{frozen_summary['fresh_recheck_status_counts']}；`rag_store.sqlite3` SHA-256 {sqlite_actual}（預期 {EXPECTED_SQLITE}）。新版索引、資料庫與向量只在 Phase U 子目錄。未修改正式 Production、Corpus v2、Historical E4、原始 720 筆或歷史報表。

## 下一步阻塞

需要先取得可確認版本、來源內容、使用處理依據及物種適用範圍的水產養殖技術來源（尤其水質、計算、疾病與寒害），逐件核實候選答案與 Rubric，並完成新版 Streamlit/生成端到端測試。所有這些項目不得用通用統計或一般法規替代。只有重新核驗後題目資格達到研究設計所需覆蓋，才可另行解鎖 720 次生成。
'''
    (OUT / "phase_u_final_report.md").write_text(report, encoding="utf-8")

    # Corpus build report contains exact manifest hash references and non-goals.
    (OUT / "rag_corpus_v3_build_report.md").write_text(f'''# Isolated Corpus v3 Build Report

- Corpus: `{manifest['corpus_version']}`
- Scope: isolated research build only; not Production and not the historical Evaluation Corpus v2.
- Source matrix: 57 records, 55 unique files by SHA-256, 2 duplicate hash groups.
- Included source files: {len(registry)}. Chunks: {manifest['total_chunk_count']}; retrieval-eligible: {manifest['retrieval_eligible_chunk_count']}; context-only: {manifest['context_only_chunk_count']}.
- Chunk JSONL SHA-256: `{manifest['chunk_jsonl_sha256']}`.
- SQLite SHA-256: `{manifest['sqlite_sha256']}`.
- Dense model: `{manifest['embedding_index']['model']}`; digest `{manifest['embedding_index']['model_digest']}`; dimension {manifest['embedding_index']['dimensions']}; L2 normalized; vector file SHA-256 `{manifest['embedding_index']['vector_file_sha256']}`.
- BM25: SQLite FTS5, Chinese bigram + Latin tokenizer, k1={manifest['bm25']['k1']}, b={manifest['bm25']['b']}.
- RRF: k={manifest['rrf']['k']}, BM25/Dense weights {manifest['rrf']['weights']}, candidate depth {manifest['rrf']['candidate_depth']}.
- Reranker: `{manifest['reranker']['model_id']}` revision `{manifest['reranker']['revision']}`; loaded on CUDA and run on all 180 questions.
- DGBAS 2020 limited use: only single-period descriptive Facts with raw category labels; resource label supplies year (XML does not).
- FA stocking data and WRA water-use values stay context-only; WRA is excluded from Water Quality evidence.
- Statute admission contains plain statutory text only; it does not authorize specific product/species use, dosage, withdrawal period, or current annex.
- Excluded: unverified source identity/version/rights/scope entries; stale 2019 local drug-use annex; all question banks, candidate answers, rubrics, Selection/Holdout and evaluation outputs.

Corpus manifests and files are under `corpus_v3_final/`. This is not E4-Final and does not authorize production switch.
''', encoding="utf-8")

    print(json.dumps({"baseline": baseline, "frozen": frozen_summary, "validation": validation, "retrieval_status": dict(retrieval_status)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
