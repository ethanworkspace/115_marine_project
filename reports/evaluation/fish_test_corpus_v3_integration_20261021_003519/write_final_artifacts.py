from __future__ import annotations
import collections
import datetime as dt
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]


def read_json(p):
    t = p.read_text(encoding="utf-8")
    if t.endswith("\\n"):
        t = t[:-2] + "\n"
    return json.loads(t)


def read_jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def write_json(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    manifest = read_json(WORK / "corpus_v3_manifest.json")
    dup = read_json(WORK / "duplicate_group_registration_validation.json")
    integrity = read_json(WORK / "corpus_v3_integrity_validation.json")
    sources = read_json(WORK / "source_admission_v3.json")["sources"]
    raw = read_json(WORK / "official_raw_data_integrity_report.json")["sources"]
    summary = read_json(WORK / "retrieval_and_evidence_summary.json")
    eligibility = read_jsonl(WORK / "question_eligibility_180.jsonl")
    labels = read_jsonl(WORK / "retrieved_context_relevance_labels.jsonl")
    refs = read_jsonl(WORK / "previous_reference_candidates_revalidation_15.jsonl")
    smoke = read_jsonl(WORK / "generator_smoke_results.jsonl")
    e2e = read_json(WORK / "rag_v3_real_e2e_validation.json")
    app = read_json(WORK / "streamlit_v3_validation.json")
    pytest = read_json(WORK / "repository_pytest_results.json")
    readiness = read_json(WORK / "evaluation_readiness_v3.json")
    coverage = read_json(WORK / "six_species_evidence_coverage.json")

    manifest["duplicate_groups"] = {
        "count": dup["duplicate_group_count"],
        "member_records": dup["duplicate_member_record_count"],
        "groups": dup["groups"],
        "policy": "All source records retained; duplicate records share provenance group; retrieval keeps one highest-ranked candidate per duplicate group."
    }
    write_json(WORK / "corpus_v3_manifest.json", manifest)

    calls = [r for r in smoke if r.get("scenario") == "SUPPORTED_POSITIVE_REAL_GENERATOR"]
    direct_ok = [r for r in calls if r.get("answer_origin") == "MODEL_GENERATED" and r.get("citation_validation", {}).get("status") == "PASS"]
    fallback = [r for r in calls if r.get("answer_origin") == "DETERMINISTIC_EVIDENCE_EXTRACTION"]
    e2e["summary"] = {
        "status": "PARTIAL_PASS_SAFE_SYSTEM_PATH; ONE_MODEL_DIRECT_CITATION_REJECTED_AND_FALLBACK_USED",
        "real_generator_calls": len(calls), "direct_model_answers_with_valid_citation": len(direct_ok),
        "model_responses_rejected_by_citation_validator": sum(1 for r in calls if r.get("citation_validation", {}).get("status") == "FAIL"),
        "deterministic_extraction_fallbacks": len(fallback),
        "negative_gate_probes": len(e2e.get("negative_probes", {})),
        "negative_probes_called_generator": sum(1 for r in e2e.get("negative_probes", {}).values() if r.get("generator_called")),
        "human_gold": 0,
        "interpretation": "All four model APIs were called once on the supported positive case. M2-M4 returned directly usable cited answers. M1's citation was rejected because its cited chunk did not contain the frozen required value; the deterministic source-span fallback returned the supported answer. Four negative cases were stopped before generation. This is a small smoke test, not a full evaluation."
    }
    write_json(WORK / "rag_v3_real_e2e_validation.json", e2e)

    source_counts = {s["source_id"]: s.get("record_counts", {}) for s in sources}
    integrity_status = "PASS" if integrity["all_automated_checks_pass"] else "FAIL"
    p5 = summary["p_at_5"]
    elig_counts = collections.Counter(r.get("eligibility_status") for r in eligibility)
    diag_counts = collections.Counter(r.get("evidence_status") for r in labels)
    source_summaries = []
    for s in sources:
        source_summaries.append({
            "source_id": s["source_id"], "dataset_id": s.get("dataset_id"), "title": s.get("title"),
            "owner_admission_status": s.get("owner_admission_status"), "license_scope_status": s.get("license_scope_status"),
            "identity_status": s.get("identity_status"), "version_status": s.get("version_status"),
            "applicability_status": s.get("applicability_status"), "completeness_status": s.get("completeness_status"),
            "records": source_counts.get(s["source_id"], {}), "source_sha256": s.get("source_sha256"), "resource_url": s.get("resource_url")
        })

    report = f"""# Corpus v3 整合與評測準備結果

執行時間：{dt.datetime.now().astimezone().isoformat()}

## 結果摘要

- 已建立隔離研究 Corpus `{manifest['corpus_id']}`，版本 `{manifest['corpus_version']}`，SQLite SHA-256：`{manifest['sqlite']['database_sha256']}`。
- 納入 4 個來源、4 個不同原始 SHA-256、12,475 筆來源紀錄、2,363 個 Chunk。2,354 個 Chunk 可檢索，9 個鰻魚放養統計 Chunk 僅供情境參考。其餘 10,735 筆來源紀錄因內容或範圍閘被排除，並非把所有原始紀錄直接編入索引。
- 180 題均重新執行 BM25、BGE-M3 Dense、RRF、來源／物種閘及 BGE Reranker。177 題取得至少一個合格 Context，133 題取得完整 Top-5，總計 792 段。
- 自動內容篩檢只找到 2 段「部分支持」候選、19 段主題線索、771 段低詞項重疊診斷，沒有一段被本輪確立為完整支持。這些是保守自動診斷，不能當成人工相關性真值或正式不相關標籤。
- 題目資格為 1 題 `PARTIALLY_SUPPORTED`、179 題 `NOT_EVALUABLE`。沒有題目被升格成已核驗完整答案。P@5、Logical Accuracy、Arithmetic Accuracy 的有效樣本數均為 0；Human Gold 為 0。
- 四模型各進行 1 次有證據的真實生成呼叫，另有 4 個生成前安全閘測例。M2–M4 的回答通過引用檢查；M1 引用的段落不含要求數值，被驗證器拒絕後使用有原文依據的確定性擷取。此結果是小型系統 smoke test，不是完整模型評測。
- Streamlit AppTest 使用同一隔離 Corpus 完成一次真實 M2 呼叫並通過。Repository pytest 未執行：可用 Python 環境均未安裝 pytest；沒有安裝套件或繞過限制。

## 新准入來源與原件

三份新核准來源的 Owner Admission、政府資料開放授權、來源身分、版本快照、適用性與檢索資格分開記錄於 `source_admission_v3.json`。Owner Admission 不替代授權，也不擴及連結的外部文件。三份原始 JSON 均與已保存快照 checksum 相符：

| Dataset | 原始筆數 | SHA-256 | 範圍限制 |
|---|---:|---|---|
| 114846 水產試驗所漁業問答 | 956 | `66e1803c1bac11aef1dd887c798767773603e1c1274d274cafa153c36a318446` | 逐筆沿用原始魚種與問答文字；不把連結外部頁面納入。 |
| 7274 動物用藥資訊 | 9,999 | `49cb8818b25dd8ec8ef7f2b9c5e86163f90d95ebeb80b3cc34c0408499228c4c` | API 完整性未知；不得推導劑量、頻率、停藥期或目前治療建議。 |
| 41845 鰻魚放養量統計 | 9 | `919201c2605e70d01c1d46270e9740714883608dcf75f9ae9fab16838bb63528` | 沒有統計年度，9 個 Chunk 均為 `CONTEXT_ONLY`。 |

三份來源頁面：[114846](https://data.gov.tw/dataset/114846)、[7274](https://data.gov.tw/dataset/7274)、[41845](https://data.gov.tw/dataset/41845) 標示政府資料開放授權條款第1版；授權文字與署名要求依[官方授權頁](https://data.gov.tw/license)記錄，第三方內容仍不在授權範圍內。既有 DGBAS 2020 XML 維持原有限範圍准入，1511 個欄位值均與原始 XML 對應；年份依官方資源標籤，沒有從 XML 缺漏欄位推定年份。

## Corpus 與來源重複關係

Corpus 僅包含上述三份來源及已有限准入的 DGBAS 2020 XML。沒有匯入 Phase AA 的 27 張候選卡、50 份全文使用依據未核實的文件、S08/S10 待核實材料或其他舊候選來源。

登錄兩組完全重複 Record（TFRI 2 筆、動物用藥 2 筆）。原始紀錄全部保留，透過 `duplicate_group_id` 留存關係；檢索每組只保留最高排名候選，沒有刪除原始資料。

六魚種 Chunk 數量只代表原始紀錄中出現明確魚種字串的範圍盤點，不等於專家認證的知識覆蓋：

| 魚種 | 字串範圍 Chunk | 對應紀錄 | 180 題有 Context | 完整 Top-5 |
|---|---:|---:|---:|---:|
{chr(10).join(f"| {sp} | {v['literal_source_chunk_count']} | — | {v['with_any_context']} | {v['full_top5']} |" for sp, v in coverage['species'].items())}

水試所來源在六魚種中提供有用的原始問答片段，但並非每一片段均能回答測試題所要求的數值、條件或處置。動物用藥來源只支持其欄位直接記載的許可資料。鰻魚放養量統計不支持年度趨勢或養殖建議。

## 180 題證據與指標資格

本輪保留 180 個原始 Question ID、題目文字與魚種。所有 Top-5 Chunk 均以 Chunk ID、來源紀錄 ID、原始 JSON 欄位定位、來源版本及 checksum 回查。各題的 `BM25 candidates → Dense candidates → RRF → scope filter → reranker → Top-5` 數量保存在 `retrieval_results_v3_180.jsonl`。

本輪 792 筆標籤由保守的確定性詞項與資料範圍篩檢產生。標籤列保留命中元素、缺少值／條件／單位、原始定位和方法；不是人工二元標註。因缺乏可靠的 Relevant／Irrelevant 標籤，不能計算 P@5。沒有凍結答案與 Rubric 的題目也不能計入 Logical 或 Arithmetic Accuracy。

Phase AA 的 15 筆舊答案候選逐筆保留歷史狀態並重新檢查。其 13 筆自動來源核驗候選所用的 TFRI 手冊或 FA-385 資料不在目前四個准入來源中，故 0 筆可直接繼承到 Corpus v3；這表示本版沒有重驗，不表示歷史來源或答案必然錯誤。歷史標籤未被修改。

## 真實系統 smoke 與尚未通過項目

- M1：模型 API 有回應，但所引用 Chunk 沒有凍結需求數值，遭 Citation Validator 拒絕；系統以驗證過的來源 Span 作確定性擷取，輸出來源已另標示，不計為 M1 模型直接回答成功。
- M2、M3、M4：在單一烏魚溶氧問題各產生一次可引用回答並通過支持值檢查。M3 的模型身分為 DeepSeek-R1-Distill-Llama-8B（Llama 家族），不是另一個 `deepseek-r1:8b` Qwen3 標籤。
- 4 個負向探測涵蓋缺值、魚種衝突、藥品高風險問題與無支持來源；均在 Generator 呼叫前拒答。
- Streamlit AppTest 確認使用 Corpus v3、呼叫真實 M2、顯示引用且無例外。
- Repository pytest 因 pytest 套件缺失而未執行，不能報為 PASS。

## 後續評測就緒狀態

- **系統技術：** 隔離 Corpus、檢索、reranker、四模型 API smoke 與 Streamlit 已實際接通。M1 直接引用失敗被安全攔截；Repository pytest 尚未執行，因此完整系統驗收仍為部分通過。
- **可計分性：** P@5、Logical Accuracy、Arithmetic Accuracy 均為 N=0；沒有可在新生成前凍結的完整答案/Rubric 子集。
- **代表性：** 目前專業原始證據以官方問答為主，另有用藥許可事實、鰻魚背景統計及 DGBAS 統計；不能視為六魚種全面的養殖、水質、疾病、氣候、計算及用藥知識庫。
- **720 次評測：** 本輪未執行。建議在取得可計分答案子集與完整 pytest/E2E 驗收後另行排程，不把本輪 smoke 當成正式評分。

## 基線保護

本輪指定 636 筆 Frozen Manifest 最終核對為 {integrity['protected_baseline']['unchanged']}/636 未變。正式 `rag_store.sqlite3` SHA-256 為 `{integrity['protected_baseline']['production_sqlite']['actual_sha256']}`，與預期值相同。Production、Evaluation Corpus v2、Historical E4、Phase E/W 原始生成均未改寫。

完整逐筆記錄、來源登錄、原文定位、檢索候選、標籤診斷、模型 smoke、測試狀態及一致性檢查均保存在本工作區。
"""
    (WORK / "phase_corpus_v3_integration_final_report.md").write_text(report, encoding="utf-8")

    compatibility = {
        "workspace": str(WORK), "created_at_local": dt.datetime.now().astimezone().isoformat(),
        "corpus_version": manifest["corpus_version"], "corpus_sha256": manifest["sqlite"]["database_sha256"],
        "new_research_outputs_written_only_to_workspace": True,
        "historical_production_corpus_and_e4_modified": False,
        "original_phase_e_and_w_generation_modified": False,
        "frozen_manifest_636_status": integrity["protected_baseline"]["status_counts"],
        "production_sqlite_matches_expected": integrity["protected_baseline"]["production_sqlite"]["matches"],
        "integrity_validation": integrity["all_automated_checks_pass"],
        "pytest": pytest["status"], "streamlit": app["status"],
        "e2e_smoke_status": e2e["summary"]["status"],
        "full_720_generation_performed": False, "winner_selected": False,
        "context_precision_p5": "NOT_EVALUABLE_N=0", "logical_accuracy": "NOT_EVALUABLE_N=0", "arithmetic_accuracy": "NOT_EVALUABLE_N=0", "human_gold": 0,
    }
    write_json(WORK / "compatibility.json", compatibility)
    print(json.dumps({"report": str(WORK / "phase_corpus_v3_integration_final_report.md"), "compatibility": compatibility}, ensure_ascii=True))


if __name__ == "__main__":
    main()
