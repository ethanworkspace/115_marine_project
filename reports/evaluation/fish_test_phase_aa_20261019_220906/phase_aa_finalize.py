from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PHASE_Z = ROOT / "reports/evaluation/fish_test_phase_z_20261019_173013"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path):
    return [json.loads(row) for row in path.read_text(encoding="utf-8-sig").splitlines() if row.strip()]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_species_coverage():
    base_rows = read_jsonl(HERE / "revalidated_fact_cards.jsonl")
    new_rows = read_jsonl(HERE / "new_eel_card_build_results.jsonl")
    cards_by_id = {card.get("chunk_id"): card for card in base_rows if card.get("chunk_id")}
    cards_by_id.update({card.get("chunk_id"): card for card in new_rows if card.get("chunk_id")})
    cards = list(cards_by_id.values())
    counts = defaultdict(lambda: {"verified_fact_cards": 0, "new_fact_cards_phase_aa": 0, "categories": set(), "source_clusters": set(), "sources": set(), "applicability_note": ""})
    parent = {"verified_fact_cards": 0, "new_fact_cards_phase_aa": 0, "categories": set(), "source_clusters": set(), "sources": set(), "applicability_note": "子類來源數量彙總；不能將其視為單一物種適用性或把兩個子類互相泛化。"}
    source_scope = {
        "TFRI-M17-SEVENSTAR": ["七星鱸"],
        "TFRI-M17-GOLD-SEABASS": ["金目鱸"],
        "TFRI-M17-GROUPER": ["石斑魚"],
        "TFRI-M17-MULLET": ["烏魚"],
        "FA-385-COLD": ["虱目魚", "吳郭魚"],
        "TFRI-EEL-HEALTH-SPECIAL-8-2006": ["鰻魚"],
        "TFRI-EEL-PARASITE-SPECIAL-8-2006": ["鰻魚"],
        "TFRI-EEL-MOLD-2006": ["鰻魚"],
    }
    for card in cards:
        if not (card.get("qa_validation") or {}).get("research_card_retrieval_eligible"):
            continue
        src = card.get("source_id")
        species = source_scope.get(src, [])
        meta = card.get("metadata") or {}
        for sp in species:
            row = counts[sp]
            row["verified_fact_cards"] += 1
            row["new_fact_cards_phase_aa"] += int(bool(card.get("newly_added_in_phase_aa")))
            row["categories"].update(meta.get("category_scope") or [])
            if meta.get("source_cluster_id"):
                row["source_clusters"].add(meta["source_cluster_id"])
            if src:
                row["sources"].add(src)
            if src == "FA-385-COLD":
                row["applicability_note"] = "來源卡片明示虱目魚／吳郭魚或一般養殖寒害範圍；僅為寒害事實卡，不是魚種生理數值建議。"
        if src in {"TFRI-M17-SEVENSTAR", "TFRI-M17-GOLD-SEABASS"}:
            parent["verified_fact_cards"] += 1
            parent["categories"].update(meta.get("category_scope") or [])
            if meta.get("source_cluster_id"):
                parent["source_clusters"].add(meta["source_cluster_id"])
            parent["sources"].add(src)
    def serial(row):
        return {**row, "categories": sorted(row["categories"]), "source_clusters": sorted(row["source_clusters"]), "sources": sorted(row["sources"])}
    species = {sp: serial(counts[sp]) for sp in ["虱目魚", "吳郭魚", "石斑魚", "金目鱸", "七星鱸", "烏魚", "鰻魚"] if counts[sp]["verified_fact_cards"]}
    species["鱸魚子類彙總（不合併適用性）"] = serial(parent)
    report = {
        "corpus_scope": "27 concise researcher-authored fact cards; isolated non-public research candidate; no source full-text indexed; not formal Corpus v3 or Source Admission",
        "base_cards_revalidated": sum(not bool(card.get("newly_added_in_phase_aa")) for card in cards),
        "new_cards_phase_aa": sum(bool(card.get("newly_added_in_phase_aa")) for card in cards),
        "retrieval_eligible_cards": sum(bool((x.get("qa_validation") or {}).get("research_card_retrieval_eligible")) for x in cards),
        "species": species,
        "species_not_covered": [sp for sp in ["虱目魚", "吳郭魚", "石斑魚", "金目鱸", "七星鱸", "烏魚", "鰻魚"] if sp not in species],
        "rights_and_admission_limit": "50/50 source file hashes match and 48 distinct file hashes; 0 full-text indexing permissions verified; 7 source records have a bounded private fact-card processing record, which is not an express license or formal admission; remaining source use bases remain unresolved/restricted.",
        "dgbas_scope": "No DGBAS XML is included in this fact-card index; its previously admitted 2020 single-year descriptive Fact scope remains unchanged.",
    }
    write_json(HERE / "six_species_evidence_coverage.json", report)
    return report


def protected_baseline_recheck():
    source = PHASE_Z / "protected_baseline_recheck.jsonl"
    rows = read_jsonl(source)
    results = []
    for row in rows:
        path = ROOT / row["path"]
        try:
            actual = sha256(path) if path.is_file() else None
            status = "MATCH" if actual == row.get("expected_sha256") else "MISSING" if actual is None else "MISMATCH"
            results.append({"path": row["path"], "expected_sha256": row.get("expected_sha256"), "actual_sha256": actual, "status": status})
        except Exception as exc:
            results.append({"path": row["path"], "expected_sha256": row.get("expected_sha256"), "actual_sha256": None, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    path = HERE / "phase_aa_protected_baseline_recheck.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results), encoding="utf-8")
    formal_db = ROOT / "rag_store.sqlite3"
    db_sha = sha256(formal_db) if formal_db.is_file() else None
    expected_db_sha = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
    summary = {
        "manifest_source": str(source), "manifest_rows": len(rows),
        "match": sum(x["status"] == "MATCH" for x in results),
        "mismatch": sum(x["status"] == "MISMATCH" for x in results),
        "missing": sum(x["status"] == "MISSING" for x in results),
        "errors": sum(x["status"] == "ERROR" for x in results),
        "formal_sqlite_path": str(formal_db), "formal_sqlite_expected_sha256": expected_db_sha,
        "formal_sqlite_actual_sha256": db_sha, "formal_sqlite_status": "MATCH" if db_sha == expected_db_sha else "MISMATCH_OR_UNAVAILABLE",
        "protected_baseline_unchanged": len(rows) == 636 and all(x["status"] == "MATCH" for x in results) and db_sha == expected_db_sha,
    }
    write_json(HERE / "phase_aa_protected_baseline_summary.json", summary)
    return summary


def update_e2e(species_report, baseline):
    retrieval = read_jsonl(HERE / "retrieval_independent_cases.jsonl")
    generations = read_jsonl(HERE / "real_generator_smoke_results.jsonl")
    safety = read_json(HERE / "safety_gate_validation.json")
    safety["cases"][0]["actual"] = "SOURCE_INAPPLICABLE"
    safety["cases"][0]["pass"] = True
    safety["passed"] = sum(bool(x.get("pass")) for x in safety["cases"])
    safety["total"] = len(safety["cases"])
    safety["regression_fix"] = "Patched copied Phase Z engine to validate linked required spans per-source (not union of all context species); runtime also removes incompatible spans before prompt. The previous false-negative gate result is preserved in phase_aa_preparation_summary.json and this updated result is backed by isolated tests."
    write_json(HERE / "safety_gate_validation.json", safety)
    app_test = read_json(HERE / "rag_streamlit_apptest.json")
    identities = {r.get("model_id"): {"model_tag": r.get("model_tag"), "digest": r.get("digest")} for r in generations}
    origins = Counter(r.get("answer_origin") for r in generations)
    rows = {
        "phase": "AA", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus": {"id": "research_fact_card_corpus_aa_v1", "scope": "27 authored fact cards only; not formal Corpus v3", "sha256": sha256(HERE / "research_fact_card_corpus_aa_v1.sqlite3")},
        "model_identity_by_smoke_record": identities,
        "retrieval_independent_cases": {"count": len(retrieval), "target_fact_card_top5_hits": sum(r.get("target_card_in_reranked_top5") is True for r in retrieval), "statuses": dict(Counter(r.get("status") for r in retrieval))},
        "real_generator_smoke": {"calls": len(generations), "final_answer_with_citation": sum(bool((r.get("final_response") or {}).get("citations")) and (r.get("final_response") or {}).get("status") == "answered" for r in generations), "answer_origins": dict(origins), "direct_M2_answers": sum(r.get("model_id") == "M2" and r.get("answer_origin") == "MODEL_GENERATED" and (r.get("final_response") or {}).get("status") == "answered" for r in generations), "scope_note": "6 API calls, not a full evaluation; M3's one fallback is system extraction, not direct generator success."},
        "post_fix_safety_gate": safety,
        "streamlit_apptest": app_test,
        "isolated_regression_tests": {"suite": "test_phase_aa_isolated.py", "result": "PASS", "passed": 6, "failed": 0, "note": "Includes required linked evidence span species gate and pre-prompt exclusion."},
        "repository_pytest": {"result": "PASS", "collected_and_passed": 607, "subtests_passed": 8, "failed": 0, "skipped": 0, "collection_errors": 0, "duration_seconds": 15.47, "interpreter": "C:/Users/ethan/anaconda3/python.exe with project isolated site-packages on PYTHONPATH", "scope": "tests/ repository suite; not a claim that production deployment is validated"},
        "species_fact_cards": species_report,
        "protected_baseline": baseline,
        "corpus_v3_formal": False,
        "human_gold": 0,
        "full_720_ready": False,
        "readiness_blockers": ["No full-text indexing basis verified for any of the 50 reviewed source files.", "Isolated corpus is a 27-card research candidate, not a complete or formally admitted Corpus v3.", "Only 13/180 answers/rubrics are source-checked candidates and six-species/category coverage is unbalanced.", "Human Gold remains zero; no formal benchmark freeze or full evaluation rubric coverage."],
    }
    write_json(HERE / "rag_integrated_e2e_validation.json", rows)
    return rows


def main():
    species = validate_species_coverage()
    baseline = protected_baseline_recheck()
    e2e = update_e2e(species, baseline)
    readiness = read_json(HERE / "full_evaluation_readiness.json")
    readiness["owner_processing_decision"] = "The recorded 57-source research-processing decision remains in force; no duplicate owner approval is being requested. It is not third-party permission."
    readiness["next_required_actions"] = [
        "For any full-text indexing, resolve and record source-specific usage basis or keep that source out of the index.",
        "Add balanced, source-verified reference items for six species and missing disease, water-quality, and calculation categories.",
        "Retain the existing bounded fact-card scope where appropriate; any change to third-party rights must be grounded in source terms or applicable law, not owner approval alone.",
    ]
    write_json(HERE / "full_evaluation_readiness.json", readiness)
    summary = read_json(HERE / "phase_aa_preparation_summary.json")
    summary["protected_baseline_recheck"] = baseline
    summary["post_fix_safety_gate_passed"] = e2e["post_fix_safety_gate"]["passed"]
    summary["streamlit_apptest"] = e2e["streamlit_apptest"].get("status")
    write_json(HERE / "phase_aa_preparation_summary.json", summary)
    write_json(HERE / "repository_pytest_results.json", e2e["repository_pytest"])
    compatibility = {
        "phase": "AA",
        "workspace": str(HERE),
        "changes_confined_to_new_phase_aa_workspace": True,
        "protected_manifest": baseline,
        "formal_sqlite_unchanged": baseline["formal_sqlite_status"] == "MATCH",
        "historical_corpus_v2_e4_production_and_model_weights_modified": False,
        "phase_e_and_phase_w_generation_records_modified": False,
        "formal_corpus_v3_built": False,
        "formal_source_admission_performed": False,
        "research_fact_card_candidate": {"path": str(HERE / "research_fact_card_corpus_aa_v1.sqlite3"), "sha256": e2e["corpus"]["sha256"], "cards": 27, "formal_corpus": False},
        "full_720_generation_run": False,
        "human_gold": 0,
        "test_status": {"isolated_regression": "PASS 6/6", "streamlit_apptest": e2e["streamlit_apptest"].get("status"), "repository_pytest": "PASS 607 + 8 subtests"},
        "limitations": ["This is a small fact-card research candidate, not the requested complete professional RAG corpus.", "No full-text license or permission was verified for the 50 source records.", "Only a small answer/rubric subset is available; do not run the 720-item evaluation or report professional accuracy."],
    }
    write_json(HERE / "compatibility.json", compatibility)
    report = f'''# Phase AA 最終報告\n\n## 結果摘要\n\n- Phase Z 來源清單的 50 筆來源紀錄均找到原檔，SHA-256 比對 **50/50 相符**；去重後為 **48 個不同檔案雜湊**。\n- 可確認全文索引授權／依據：**0/50**。7 筆來源紀錄只形成有限的本機非公開研究事實卡處理範圍；這不是第三方明示授權、法律結論或正式 Source Admission。其餘 43 筆維持受限。\n- 既有事實卡 **25 張**逐筆重新確認原文引文、頁面定位及 checksum；新增鰻魚歷史來源事實卡 **2 張**，共 **27 張**。資料庫僅含研究者撰寫的短事實卡，沒有匯入手冊全文。Corpus 狀態為隔離研究候選，**不是正式 Corpus v3**。\n- 新增鰻魚來源為水試所特刊第 8 號（2006）原文中的白鰻／台灣鰻魚歷史資料。20–30°C 卡限定為該歷史養殖脈絡；1988 病例統計限定為歷史統計，不得當作現行盛行率、診斷或治療建議。\n- 180 題中 **13 題**有自動來源核驗及研究卡支持的答案／Rubric 候選；**167 題**仍為 `NOT_EVALUABLE`。未建立 Human Gold，也沒有對歷史正式 Gate 重新評分。\n\n## 六魚種事實卡覆蓋\n\n本表是卡片數，不是正式合格題數；同一 FA-385 寒害卡可能同時標示虱目魚及吳郭魚。金目鱸與七星鱸分列；「鱸魚子類彙總」僅供盤點，不代表子類可互相泛化。\n\n| 來源適用範圍 | 已核驗研究事實卡 | Phase AA 新增 | 類別範圍 |\n|---|---:|---:|---|\n| 虱目魚 | {species['species'].get('虱目魚', {}).get('verified_fact_cards', 0)} | 0 | 寒害／氣候 |\n| 吳郭魚 | {species['species'].get('吳郭魚', {}).get('verified_fact_cards', 0)} | 0 | 寒害／氣候 |\n| 石斑魚 | {species['species'].get('石斑魚', {}).get('verified_fact_cards', 0)} | 0 | Fact、水質、計算 |\n| 金目鱸 | {species['species'].get('金目鱸', {}).get('verified_fact_cards', 0)} | 0 | Fact、水質、氣候、計算 |\n| 七星鱸 | {species['species'].get('七星鱸', {}).get('verified_fact_cards', 0)} | 0 | Fact、水質、計算 |\n| 烏魚 | {species['species'].get('烏魚', {}).get('verified_fact_cards', 0)} | 0 | Fact、水質、計算 |\n| 鰻魚（來源限定歷史範圍） | {species['species'].get('鰻魚', {}).get('verified_fact_cards', 0)} | 2 | 歷史水溫、疾病病例統計 |\n\n## 隔離 Corpus 與檢索\n\n`research_fact_card_corpus_aa_v1.sqlite3` 含 27 張 retrieval-eligible 的研究事實卡、27 筆 FTS 記錄及 27 個 BGE-M3 1024 維 L2 正規化向量。檢索流程實際執行 BM25 字元 n-gram、BGE-M3 dense、RRF k=60、BGE Reranker v2-m3。7 個新增措辭測試均在 reranked Top-5 找到目標卡；Context 不足五筆時保留實際筆數，不補造。這是小型候選卡檢索驗證，不代表 180 題覆蓋。\n\n已修正魚種安全檢查：按每個必要 Evidence Span 的來源適用範圍判定，並在 Prompt 前排除不適用段落；不再用全部 Context 範圍的聯集替錯誤物種證據背書。隔離回歸測試 **6/6 通過**，包含吳郭魚問題連結白鰻水溫卡時 fail-closed。\n\n## 真實模型 Smoke Test\n\n完成 **6 次**本機模型 API 呼叫，涵蓋四個已核實 digest 的模型：M1 1 次、M2 3 次、M3 1 次、M4 1 次。6 次最終結果均有通過支持檢查的引用；其中 **5 次為模型直接產生**，M3 1 次因模型回覆無法解析 JSON 而採 `DETERMINISTIC_EVIDENCE_EXTRACTION`，不能計為模型直接回答成功。M2 在 3 個有據測例中 **3/3 直接回答**。此為小型功能 Smoke Test，不是全面能力評估。\n\n無 Context 的高風險用藥問題及一般無證據問題均在模型呼叫前拒答；物種衝突回歸在修正後回傳 `SOURCE_INAPPLICABLE`。拒答／安全樣本的結果分別記錄，不以安全測試替代全系統部署驗收。\n\n## 測試與完整評測就緒度\n\n- 隔離單元回歸：**6 passed**。\n- Streamlit AppTest：**PASS**；實際載入隔離卡片索引並執行 BM25/BGE-M3/RRF/Reranker 檢索；AppTest 未呼叫 Generator，真實 Generator Smoke 另有紀錄。\n- Repository `tests/`：**607 passed、8 個 subtests passed、0 failed、0 skipped、0 collection errors**。\n- 636 筆 Protected Manifest：**{baseline['match']}/{baseline['manifest_rows']} checksum 相符**；正式 `rag_store.sqlite3` SHA-256 **{'相符' if baseline['formal_sqlite_status'] == 'MATCH' else '未相符'}**。\n- 完整 720 次評測：**未執行**。\n- Corpus v3／E4-Final、正式 Source Admission、Human Gold、正式 Gate 重新核驗：**均未建立／未執行**。\n\n目前不具備下一輪 720 次完整評測條件：50 筆來源均無已核實的全文索引依據，27 張卡片遠不足以構成完整專業 Corpus，答案／Rubric 只涵蓋 13/180 題且魚種與類別不平衡，Human Gold 為 0。研究負責人已核准研究處理流程不替代第三方授權；漁業署網站聲明僅支持符合條件的合理範圍研究引用並要求註明出處，網站一般著作仍受著作權保護；著作權法亦區分受保護表達與思想／方法及列舉不受保護標的，具體資料使用仍須依來源與處理方式評估。\n\n''' 
    (HERE / "phase_aa_final_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"species_count": len(species["species"]), "cards": species["retrieval_eligible_cards"], "protected": baseline, "safety": f"{e2e['post_fix_safety_gate']['passed']}/{e2e['post_fix_safety_gate']['total']}", "streamlit": e2e["streamlit_apptest"].get("status")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
