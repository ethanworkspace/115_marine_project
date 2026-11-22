from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\my project\115_marine_project")
OUT = ROOT / "reports/evaluation/fish_test_phase_ab_20261020_164748"
STAGE = ROOT / "research_staging/source_qualification/phase_ab_20261020_164748"
AA = ROOT / "reports/evaluation/fish_test_phase_aa_20261019_220906"
OUT.mkdir(parents=True, exist_ok=True)
STAGE.mkdir(parents=True, exist_ok=True)

def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_jsonl(name, rows):
    (OUT / name).write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")

captured_at = "2026-10-20T16:47:48+08:00"
ogl = {
    "license_name": "政府資料開放授權條款-第1版 (OGL v1)",
    "license_url": "https://data.gov.tw/license",
    "dataset_page_declares_license": True,
    "summary": "對明確以 OGL v1 釋出的開放資料，條款授予不限目的、時間及地域的非專屬、免權利金利用權，包含重製、編輯及改作；須按附件顯名並尊重第三人著作人格權。授權僅依具體資料集／資源的釋出標示判斷，不自動延伸至外連網站的全部頁面、圖片或第三方內容。",
    "attribution_template": "農業部／資料提供單位 [資料年份] [開放資料釋出名稱與版本號]；此開放資料依政府資料開放授權條款（Open Government Data License）釋出；https://data.gov.tw/license",
    "third_party_rights_caveat": "OGL 定義及免責條款保留第三人權利風險；若資料集包含第三人著作或未明確納入開放資料的外連內容，須另行核查。",
    "basis_type": "dataset_specific_open_license_as_declared_on_data.gov.tw",
    "not_third_party_individual_permission": True,
}

datasets = [
    {
        "dataset_id": "114846", "source_id": "DGTW-114846-TFRI-QA", "title": "水產試驗所漁業問答",
        "publisher": "農業部（水產試驗所）", "metadata_url": "https://data.gov.tw/dataset/114846",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/TfrinRss/TfrinRss02.aspx?IsTransData=1&UnitId=B71",
        "resource_formats": ["JSON", "CSV", "XML"], "fields": ["title", "link", "description（回答）", "pubdate"],
        "metadata_updated": "2023-08-14 16:35", "update_frequency": "不定期更新", "license": "政府資料開放授權條款-第1版",
        "raw_download_status": "not_saved_raw_payload", "raw_sha256": None,
        "observation": "官方資料集頁面欄位、提供機關及 OGL v1 可核對；資源 feed 可由官方開放資料介面檢視，但本輪未保存完整原始 bytes。僅抽查特定記錄；不能據此計算全資料集魚種／主題總數。",
        "candidate_scope": "僅考慮資料資源中的單筆 title/link/description/pubdate 記錄及其自述內容；不自動納入外連 TFRI 網頁完整文字、圖片或附件。",
        "owner_admission_status": "pending_new_owner_decision", "formal_corpus_status": "not_included",
    },
    {
        "dataset_id": "18290", "source_id": "DGTW-18290-MOJ-LAW-ZIP", "title": "中文法規_命令資料檔下載",
        "publisher": "法務部資訊處", "metadata_url": "https://data.gov.tw/dataset/18290",
        "resource_url": "https://sendlaw.moj.gov.tw/",
        "resource_formats": ["ZIP"], "fields": ["法規性質", "法規名稱", "法規網址", "法規類別", "最新異動日期", "生效日期", "生效內容", "廢止註記", "附件", "沿革內容", "前言", "條號", "條文內容", "英譯註記／英文名稱"],
        "metadata_updated": "2025-09-08 11:24", "update_frequency": "每月", "license": "政府資料開放授權條款-第1版",
        "raw_download_status": "download_not_completed", "raw_sha256": None,
        "observation": "資料集頁面確認 ZIP 原始資料型資源、欄位及 OGL v1 標示；ZIP bytes 本輪未取得，未核對內含法規版本、檔案數或 checksum。",
        "candidate_scope": "未取得原件前無內容進入證據集；若後續使用，限由法規原始條文、沿革及生效日期支持的法律事實。",
        "owner_admission_status": "pending_new_owner_decision", "formal_corpus_status": "not_included",
    },
    {
        "dataset_id": "7274", "source_id": "DGTW-7274-APHIA-ANIMAL-DRUG", "title": "動物用藥資訊",
        "publisher": "農業部動植物防疫檢疫署", "metadata_url": "https://data.gov.tw/dataset/7274",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx",
        "resource_formats": ["JSON", "CSV", "XML"], "fields": ["許可證字號", "中文／英文品名", "業者及製造廠", "劑型", "包裝", "效能（適應症）", "成分", "核發日期", "有效期間", "外銷專用"],
        "metadata_updated": "2026-03-13 03:15（資料集詮釋資料）", "update_frequency": "每7天", "license": "政府資料開放授權條款-第1版",
        "raw_download_status": "payload_exceeds_available_web_tool_limit; local_request_denied", "raw_sha256": None,
        "observation": "data.gov.tw 欄位、發布機關、更新頻率及 OGL v1 可核對；官方 API 載荷約 8.7 MB，網頁讀取工具回報超出內容大小上限，本機網路取得受 Windows 10013 限制。欄位未列目標魚種、用量或停藥期。",
        "candidate_scope": "只能作許可資料欄位的候選來源；未取得原始資料及逐藥品欄位前，不支持魚種適用、劑量或停藥日數答案。",
        "owner_admission_status": "pending_new_owner_decision", "formal_corpus_status": "not_included",
    },
    {
        "dataset_id": "41845", "source_id": "DGTW-41845-MOA-EEL-STOCKING", "title": "縣市別養殖放養量彙整表（鰻魚）",
        "publisher": "農業部", "metadata_url": "https://data.gov.tw/dataset/41845",
        "resource_url": "https://data.moa.gov.tw/Service/OpenData/DataFileService.aspx?IsTransData=1&UnitId=B36",
        "resource_formats": ["JSON"], "fields": ["所屬縣市", "魚塭口數", "魚塭面積（公頃）", "百分比", "在池放養量", "新放養量", "養殖戶數及類別"],
        "metadata_updated": "2025-04-02（資料集詮釋資料）", "update_frequency": "不定期更新", "license": "政府資料開放授權條款-第1版",
        "raw_download_status": "web_rendered_resource_observed_not_saved", "raw_sha256": None,
        "observation": "官方資源以 JSON 檢視，欄位含縣市及放養統計；檢視到縣市資料與彙總行，但回應資料列未呈現可核對的參考年度，原始 bytes 未保存。統計類別不能等同精確生物物種或管理建議。",
        "candidate_scope": "僅可能支持明確年度、地域、原始統計分類及單位均可由原始資料核對的描述性 Fact；目前因未保存原件且參考年度未核實，不建立數值 Fact。",
        "owner_admission_status": "pending_new_owner_decision", "formal_corpus_status": "not_included",
    },
]

admission_candidates = {
    "decision_version": "phase_ab_candidate_admission_v1",
    "created_at": captured_at,
    "existing_57_source_owner_decision_applies": False,
    "candidates": datasets,
    "recommendation": "四筆均可送研究負責人作來源決策；本輪沒有任何一筆進入正式 Corpus。114846 的資料資源明示 OGL v1 且可支持少量狹義候選記錄，但原始 feed bytes/完整版本未保存。其他三筆雖資料集頁面標示 OGL v1，仍須取得原始資源及核對範圍後才可解析納入。",
}
write_json("open_data_source_admission_candidates.json", admission_candidates)

download_manifest = {
    "manifest_version": "phase_ab_open_data_download_manifest_v1",
    "checked_at": captured_at,
    "downloaded_and_sha256_verified_count": 0,
    "metadata_pages_checked": 4,
    "raw_payloads_saved": 0,
    "network_notes": [
        "本機 PowerShell 取得官方域名遇到 Windows socket access error 10013；未停用 Sandbox、未放寬權限。",
        "官方瀏覽檢視可核對 metadata/部分資源呈現，但不會將瀏覽工具渲染文字保存為原始檔或計算偽 checksum。",
        "動物用藥官方 API 載荷超出可用瀏覽工具內容上限；法規 ZIP 未成功取得。",
    ],
    "resources": [
        {"dataset_id": d["dataset_id"], "source_id": d["source_id"], "official_metadata_url": d["metadata_url"], "resource_url": d["resource_url"], "raw_file_saved": False, "raw_sha256": None, "download_status": d["raw_download_status"], "version_basis": d["metadata_updated"], "version_is_resource_version": False, "license_label_on_dataset_page": d["license"]}
        for d in datasets
    ],
}
write_json("official_open_data_download_manifest.json", download_manifest)

records = [
    {
        "evidence_id": "AB-TFRI-QA-903-GROUPER-001", "dataset_id": "114846", "source_id": "DGTW-114846-TFRI-QA",
        "record_id": "TFRI-QA-903", "record_date": "2022-07-29", "original_record_url": "https://www.tfrin.gov.tw/theme_data.php?theme=qa&sub_theme=fishery&id=903",
        "species_scope": {"source_label": "石斑魚（群組用語；未給學名）", "taxonomy_level": "source_group_label", "target_scope": ["石斑魚（僅依來源原標籤）"]},
        "category": "Water Quality / Culture method descriptive fact", "exact_evidence": None,
        "factual_statement": "水試所該筆歷史問答表示，石斑魚可使用純海水養殖，並提及箱網或陸上魚塭等型態；此卡只記錄該回答的來源敘述，不形成現行、跨物種或場址通用 SOP。",
        "evidence_locator": "Dataset 114846 record id=903; pubdate=2022-07-29; linked TFRI record URL above. Exact resource payload bytes/span not retained locally.",
        "required_conditions": ["不得擴張為所有石斑魚物種或所有場址的建議", "水源交換頻率須依該回答所列池型與管理條件另行核對"],
        "numeric_values": None, "units": None, "usage_basis": "OGL v1 expressly declared on dataset 114846 resource; attribution required; applies to dataset resource, subject to third-party-rights caveat.",
        "verification_status": "WEB_RESOURCE_RECORD_OBSERVED; RAW_BYTES_AND_EXACT_SPAN_NOT_SAVED", "retrieval_eligibility": False,
        "admission_status": "CANDIDATE_PENDING_OWNER_DECISION", "human_gold": False,
    },
    {
        "evidence_id": "AB-TFRI-QA-523-TILAPIA-001", "dataset_id": "114846", "source_id": "DGTW-114846-TFRI-QA",
        "record_id": "TFRI-QA-523", "record_date": "2012-07-27", "original_record_url": "https://www.tfrin.gov.tw/theme_data.php?theme=qa&sub_theme=fishery&id=523",
        "species_scope": {"source_label": "吳郭魚養殖池問題", "taxonomy_level": "source_common_name", "target_scope": ["吳郭魚（來源原標籤）"]},
        "category": "Water Quality", "exact_evidence": None,
        "factual_statement": "該筆問答的質性說明指出，池塘有機物分解會消耗溶氧；不納入該歷史答覆中的化學處置劑量或操作建議。",
        "evidence_locator": "Dataset 114846 record id=523; pubdate=2012-07-27; linked TFRI record URL above. Full exact source span is not stored in local raw payload.",
        "required_conditions": ["僅記錄歷史答覆的質性機制", "不推廣至其他魚種的數值管理門檻", "不提供消毒藥劑及劑量"],
        "numeric_values": None, "units": None, "usage_basis": "OGL v1 expressly declared on dataset 114846 resource; attribution required; applies to dataset resource, subject to third-party-rights caveat.",
        "verification_status": "WEB_RESOURCE_RECORD_OBSERVED; RAW_BYTES_AND_EXACT_SPAN_NOT_SAVED", "retrieval_eligibility": False,
        "admission_status": "CANDIDATE_PENDING_OWNER_DECISION", "human_gold": False,
    },
    {
        "evidence_id": "AB-TFRI-QA-626-MULLET-001", "dataset_id": "114846", "source_id": "DGTW-114846-TFRI-QA",
        "record_id": "TFRI-QA-626", "record_date": "2013-08-20", "original_record_url": "https://www.tfrin.gov.tw/theme_data.php?id=626&sub_theme=fishery&theme=qa",
        "species_scope": {"source_label": "烏魚", "taxonomy_level": "source_common_name", "target_scope": ["烏魚"]},
        "category": "Water Quality", "exact_evidence": "至於烏魚對水體濁度之適應能力範圍，目前本所並無相關資料。",
        "factual_statement": "該筆 2013 年答覆明示當時水試所沒有烏魚濁度適應範圍資料；同一回答亦描述低溶氧與高濁度對烏魚屬環境緊迫，並描述高濁度會降低鰓部功能。",
        "evidence_locator": "TFRI webpage, page section 漁業問答, incoming date 102-08-20, category 魚類養殖, paragraph 2; lines 125-126 in official rendered page; physical page not applicable.",
        "required_conditions": ["這是 2013 歷史答覆的知識缺口陳述，不代表目前不存在其他研究資料", "不據此建立濁度安全值", "僅適用烏魚來源標籤"],
        "numeric_values": None, "units": None, "usage_basis": "Dataset 114846 declares OGL v1 for its data resource; direct linked webpage has separate site-level terms/copyright context and is not treated as wholly OGL. Candidate fact is limited to the licensed record field pending raw record capture and owner admission.",
        "verification_status": "OFFICIAL_WEBPAGE_SPAN_VERIFIED; DATASET_RESOURCE_BYTES_NOT_SAVED", "retrieval_eligibility": False,
        "admission_status": "CANDIDATE_PENDING_OWNER_DECISION", "human_gold": False,
    },
    {
        "evidence_id": "AB-TFRI-QA-704-MILKFISH-001", "dataset_id": "114846", "source_id": "DGTW-114846-TFRI-QA",
        "record_id": "TFRI-QA-704", "record_date": "2014-12-26", "original_record_url": "https://www.tfrin.gov.tw/theme_data.php?id=704&sub_theme=fishery&theme=qa",
        "species_scope": {"source_label": "虱目魚", "taxonomy_level": "source_common_name", "target_scope": ["虱目魚"]},
        "category": "Fact / Culture environment", "exact_evidence": "臭土味產生的主因是養殖環境不理想，而引起具臭土味的放射菌和藻類 (如顫藻、魚腥藻等) 過量繁生。",
        "factual_statement": "該筆 2014 年答覆將虱目魚臭土味主因描述為養殖環境不理想，與具臭土味的放射菌及藻類過量繁生相關；不納入原回答中的處理藥劑或操作做法。",
        "evidence_locator": "TFRI webpage, page section 漁業問答, incoming date 103-12-26, category 魚類養殖, paragraph 1; line 126 in official rendered page; physical page not applicable.",
        "required_conditions": ["僅轉述該歷史問答的來源主張", "不構成診斷、治療或防治建議", "不由此推論所有異味病例的病因"],
        "numeric_values": None, "units": None, "usage_basis": "Dataset 114846 declares OGL v1 for its data resource; linked webpage as a whole is not assumed covered by that dataset license. Candidate fact limited to data resource record pending raw capture and owner admission.",
        "verification_status": "OFFICIAL_WEBPAGE_SPAN_VERIFIED; DATASET_RESOURCE_BYTES_NOT_SAVED", "retrieval_eligibility": False,
        "admission_status": "CANDIDATE_PENDING_OWNER_DECISION", "human_gold": False,
    },
]
write_jsonl("open_data_evidence_records.jsonl", records)
write_jsonl("staging/resource_record_observations.jsonl", [
    {"dataset_id": "114846", "record_id": rid, "observation_method": "official_dataset_resource_or_linked_official_page_rendered_by_web_tool", "observation_date": "2026-10-20", "raw_bytes_saved": False, "raw_sha256": None, "source_text_status": status, "note": note}
    for rid, status, note in [
        ("TFRI-QA-903", "record_description_observed; no exact local capture", "Historical grouper water-source/culture-mode answer; group label only."),
        ("TFRI-QA-523", "record_description_observed; no exact local capture", "Historical tilapia pond organic matter/DO qualitative answer; exclude chemical rates."),
        ("TFRI-QA-626", "exact limited page span observed", "Official page content and date visible; data resource bytes not saved."),
        ("TFRI-QA-704", "exact limited page span observed", "Official page content and date visible; treatment methods excluded."),
        ("TFRI-QA-705", "record inspected", "Live fish handling context; excluded as aquaculture management evidence."),
        ("TFRI-QA-203", "record inspected", "Question mentions eel but answer pertains to tilapia; excluded as eel evidence."),
        ("TFRI-QA-156", "record inspected", "Eel processing question points to older books; no usable aquaculture fact."),
        ("TFRI-QA-154", "record inspected", "Broad old feed statement; too aged/vague for actionable eel fact."),
    ]
])

baseline_species = {
    "虱目魚": {"phase_aa_verified_fact_cards": 5, "phase_ab_candidate_facts": 1, "new_retrieval_eligible_cards": 0, "topics_added_candidate": ["Fact / historical culture environment"], "notes": "1 TFRI Q&A candidate; not in corpus."},
    "吳郭魚": {"phase_aa_verified_fact_cards": 5, "phase_ab_candidate_facts": 1, "new_retrieval_eligible_cards": 0, "topics_added_candidate": ["Water Quality / qualitative dissolved oxygen mechanism"], "notes": "1 historic Q&A candidate; no numeric SOP."},
    "石斑魚": {"phase_aa_verified_fact_cards": 4, "phase_ab_candidate_facts": 1, "new_retrieval_eligible_cards": 0, "topics_added_candidate": ["Water Quality / marine culture method"], "notes": "Source uses group label, no species-level taxonomy; not generalized."},
    "鱸魚（保留金目鱸／七星鱸子類）": {"phase_aa_verified_fact_cards": 11, "phase_ab_candidate_facts": 0, "new_retrieval_eligible_cards": 0, "topics_added_candidate": [], "notes": "No new fish-specific evidence; species subgroups stay separate."},
    "烏魚": {"phase_aa_verified_fact_cards": 3, "phase_ab_candidate_facts": 1, "new_retrieval_eligible_cards": 0, "topics_added_candidate": ["Water Quality / historical answer states tolerance range unavailable then"], "notes": "Historical epistemic claim, not a current turbidity threshold."},
    "鰻魚": {"phase_aa_verified_fact_cards": 4, "phase_ab_candidate_facts": 0, "new_retrieval_eligible_cards": 0, "topics_added_candidate": [], "notes": "Dataset 41845 is statistics without verified reference year and cannot add husbandry evidence."},
}
write_json("six_species_verified_coverage.json", {
    "as_of": captured_at,
    "prior_phase_aa_research_cards": 27,
    "phase_ab_new_candidate_evidence_records": 4,
    "phase_ab_new_retrieval_eligible_facts": 0,
    "species": baseline_species,
    "tfrin_qa_inspected_record_sample": {"records_inspected": 8, "records_mentioning_any_target_species_or_group": 8, "narrow_fact_candidates": 4, "disease_candidates": 0, "water_quality_candidates": 2, "culture_management_or_fact_candidates": 2, "climate_risk_candidates": 0, "full_dataset_total": None, "full_dataset_total_status": "not_computable_without_saved_complete_resource_payload"},
    "caveat": "The eight inspected Q&A records were a purposive sample, not a census. Candidate records are not formal admissions and are not searchable in designated Corpus.",
})

candidate_manifest = {
    "corpus_version": "phase_ab_corpus_candidate_v1",
    "build_status": "NOT_BUILT; new datasets pending owner admission and local raw-payload capture",
    "formal_corpus_v3_created": False,
    "base_phase_aa_candidate_corpus": {"id": "research_fact_card_corpus_aa_v1", "cards": 27, "sha256": "991d73e05b433896c87ee476ceef99faddbac8bfe5f493f939e121798a50b696", "formal_corpus": False},
    "new_sources": [{"dataset_id": d["dataset_id"], "source_id": d["source_id"], "raw_sha256": None, "formal_admission": False, "retrieval_eligible": False, "status": d["owner_admission_status"]} for d in datasets],
    "new_indexable_evidence_count": 0,
    "reason_blocked": ["New datasets are outside prior 57-source owner decision.", "No dataset resource raw bytes saved for checksum/version pinning.", "No resource-record complete payload integrity check performed.", "No new source Admission executed."],
    "existing_index_unchanged": True,
}
write_json("corpus_updated_manifest.json", candidate_manifest)

ref_answers = [
    {"question_id": "AB-TFRI-QA-903-Q1", "question": "依水試所該筆 2022 年問答，來源以『石斑魚』群組名稱回答其養殖水源是否可用純海水？", "reference_answer": "該歷史問答表示其所稱石斑魚可使用純海水養殖；此答案只轉述該記錄，不等同對所有石斑魚物種或所有養殖場的現行建議。", "source_id": "DGTW-114846-TFRI-QA", "record_id": "TFRI-QA-903", "source_version": "data.gov metadata 2023-08-14; record pubdate 2022-07-29; feed version not pinned", "exact_evidence_span": None, "evidence_locator": "https://www.tfrin.gov.tw/theme_data.php?theme=qa&sub_theme=fishery&id=903", "verification_status": "CANDIDATE_AUTO_SOURCE_CHECKED_LIMITED", "formal_corpus_evidence": False, "human_gold": False, "rubric": ["state source says pure seawater is usable", "retain source group label and historical scope", "no universal species or site generalization"]},
    {"question_id": "AB-TFRI-QA-523-Q1", "question": "依水試所 2012 年吳郭魚池塘問答，有機物分解會如何影響水中溶氧？", "reference_answer": "該答覆的質性說明是有機物分解消耗溶氧；不將舊答覆中的化學劑量列為建議。", "source_id": "DGTW-114846-TFRI-QA", "record_id": "TFRI-QA-523", "source_version": "data.gov metadata 2023-08-14; record pubdate 2012-07-27; feed version not pinned", "exact_evidence_span": None, "evidence_locator": "https://www.tfrin.gov.tw/theme_data.php?theme=qa&sub_theme=fishery&id=523", "verification_status": "CANDIDATE_AUTO_SOURCE_CHECKED_LIMITED", "formal_corpus_evidence": False, "human_gold": False, "rubric": ["identify dissolved oxygen consumption by decomposing organic matter", "no numeric threshold required", "do not reproduce chemical treatment instructions"]},
    {"question_id": "AB-TFRI-QA-626-Q1", "question": "水試所 2013 年答覆是否提供烏魚的濁度耐受範圍？", "reference_answer": "該答覆表示當時水試所沒有烏魚濁度適應範圍資料；這是歷史答覆狀態，不是目前沒有任何研究資料的證明。", "source_id": "DGTW-114846-TFRI-QA", "record_id": "TFRI-QA-626", "source_version": "page incoming date 2013-08-20; current page capture not locally saved; dataset metadata 2023-08-14", "exact_evidence_span": "至於烏魚對水體濁度之適應能力範圍，目前本所並無相關資料。", "evidence_locator": "TFRI Q&A record 626; official webpage paragraph 2; https://www.tfrin.gov.tw/theme_data.php?id=626&sub_theme=fishery&theme=qa", "verification_status": "CANDIDATE_SOURCE_SPAN_WEB_VERIFIED_NOT_RAW_ARCHIVED", "formal_corpus_evidence": False, "human_gold": False, "rubric": ["answer no range was provided in that answer", "attribute the statement to the 2013 response", "do not infer a current universal absence of research"]},
    {"question_id": "AB-TFRI-QA-704-Q1", "question": "依水試所 2014 年虱目魚臭土味問答，答覆所述主要相關因素為何？", "reference_answer": "該答覆將臭土味與不理想養殖環境，以及相關放射菌和藻類過度繁生聯繫；不將其延伸成個案診斷或處理指示。", "source_id": "DGTW-114846-TFRI-QA", "record_id": "TFRI-QA-704", "source_version": "page incoming date 2014-12-26; current page capture not locally saved; dataset metadata 2023-08-14", "exact_evidence_span": "臭土味產生的主因是養殖環境不理想，而引起具臭土味的放射菌和藻類 (如顫藻、魚腥藻等) 過量繁生。", "evidence_locator": "TFRI Q&A record 704; official webpage paragraph 1; https://www.tfrin.gov.tw/theme_data.php?id=704&sub_theme=fishery&theme=qa", "verification_status": "CANDIDATE_SOURCE_SPAN_WEB_VERIFIED_NOT_RAW_ARCHIVED", "formal_corpus_evidence": False, "human_gold": False, "rubric": ["identify the answer's stated environmental and microbial/algal association", "do not assert diagnosis/treatment or all-case causation"]},
]
write_jsonl("reference_answers_updated.jsonl", ref_answers)
write_json("evaluation_rubrics_updated.json", {
    "version": "phase_ab_rubrics_candidate_v1", "status": "FROZEN_CANDIDATE_ONLY; not approved benchmark rubric", "human_gold_count": 0,
    "records": [{"question_id": r["question_id"], "rubric": r["rubric"], "source_id": r["source_id"], "record_id": r["record_id"], "verification_status": r["verification_status"], "scoring": "binary element matching only if later admitted and independently rechecked", "not_evaluable_until": ["owner admission", "resource version/raw payload pinned", "full support span captured where absent"]} for r in ref_answers]
})

write_json("rag_e2e_validation.json", {
    "phase": "AB", "status": "BLOCKED_FOR_CORPUS_INTEGRATION", "candidate_records_schema_valid": True,
    "raw_source_traceability_pass": False, "new_source_usage_scope_check": "dataset pages declare OGL v1; raw resources not locally captured; source-specific release/third-party limits remain to verify against payload",
    "formal_corpus_updated": False, "bm25_bge_m3_rrf_reranker_rebuilt": False, "four_model_smoke_test_run": False,
    "streamlit_new_corpus_test_run": False, "repository_pytest_run": False,
    "reason": "Candidate sources are not yet owner-admitted, and resource payload bytes/checksums have not been captured. This phase did not change or rebuild the Phase AA candidate database.",
    "safe_claims": ["four dataset metadata pages inspected", "OGL v1 fields/attribution conditions confirmed from official terms", "four narrow Q&A evidence candidates created", "0 new cards entered designated corpus"],
})
write_json("full_evaluation_readiness.json", {
    "full_720_ready": False, "reason": ["No new dataset has completed owner admission and raw source pinning.", "No updated designated Corpus was built.", "New candidate answers are not formal corpus evidence and have no Human Gold review.", "Full TFRI Q&A feed census and coverage counts are unavailable without complete payload."],
    "phase_aa_verified_answer_candidates": 13, "phase_ab_new_candidate_answer_records": 4, "phase_ab_formal_answerable_verified_added": 0,
    "phase_ab_new_retrieval_eligible_evidence": 0, "human_gold": 0, "next_gate": "Owner admission for specific data resources, save official bytes and verify checksum/resource version, then reassess allowed scope and only then build isolated corpus.",
    "720_generation_run": False,
})

write_json("compatibility.json", {
    "phase": "AB", "output_workspace": str(OUT), "research_staging": str(STAGE),
    "historical_phase_aa_outputs_modified": False, "production_modified": False, "formal_sqlite_modified": False,
    "historical_corpus_modified": False, "raw_generations_modified": False, "full_720_run": False,
    "frozen_manifest_expected": 636, "frozen_manifest_recheck_pending": True,
    "formal_corpus_v3_built": False, "source_admission_executed": False, "human_gold": 0,
})

report = """# Phase AB — 開放授權資料取得與基準擴充摘要\n\n"""
report += f"檢查時間：{captured_at}。本輪建立四個官方資料集的 Candidate Admission 紀錄，檢視官方 metadata 及有限筆水試所問答原文；沒有把瀏覽器顯示文字冒充為原始下載檔。\n\n"
report += "## 已完成的核對\n\n"
report += "- 四個官方資料集頁面均可核對到資料集名稱、發布者／機關、資源欄位及頁面所列授權。114846、18290、7274、41845 頁面均標示政府資料開放授權條款第 1 版；該條款要求顯名並保留第三人權利限制。授權只按明示釋出的資料資源處理，不延伸到外連站的全部頁面或附件。\n"
report += "- 4/4 原始資源未保存為本機 bytes，原始 SHA-256 均為 null；所以本輪實際下載並驗證的資料檔為 0 份。法規 ZIP 未成功取得；動物用藥 API 內容超出可用瀏覽工具上限且本機連線遇到 Windows 10013；另兩個 JSON/feed 僅能檢視網頁呈現，未保存完整原始 payload。\n"
report += "- 對水試所問答只抽查 8 筆可識別記錄；8 筆提及六魚種之一或相關群組標籤，4 筆形成狹義候選事實（虱目魚、吳郭魚、石斑魚群組、烏魚各 1）。這是目的性抽查，不是完整資料集統計；沒有完整 feed bytes，疾病、水質、養殖管理、氣候主題的全資料集筆數不能可靠計算。抽查記錄中疾病 0、水質 2、狹義養殖／環境 Fact 2、氣候風險 0；其餘觀察記錄被排除或保留限制。\n"
report += "- 4 張來源候選證據卡及 4 筆參考答案候選已建立；其中 2 筆有可在官方網頁定位的短原文 span，另外 2 筆只有資料資源記錄觀察／連結，完整原文 span 未保存。所有候選均 `retrieval_eligibility=false`、`formal_corpus_evidence=false`、`human_gold=false`。\n"
report += "- 動物用藥資料欄位列有許可證、適應症、成分及效期等，但資料集 schema 未列目標魚種、實際用量或停藥期；未取得 records 前不作任何藥物安全推論。41845 是鰻魚縣市放養統計；所檢視 payload 未能核對參考年度，不能作年度 Fact 或鰻魚養殖 SOP。\n\n"
report += "## 語料與評測狀態\n\n"
report += "本輪沒有新增任何可索引的正式專業證據（0 張）。Phase AA 的 27 張隔離事實卡庫未被修改；沒有建立或更新指定 Corpus v3，沒有重建 BM25、BGE-M3、RRF、Reranker，也沒有執行四模型或 720 次生成。新的資料集均不在既有 57 筆 Owner Decision 內，現列 Candidate Admission，不代表已取得新的研究負責人核准，更不代表第三方授權。\n\n"
report += "六魚種基線卡數沿用 Phase AA 研究候選統計：虱目魚 5、吳郭魚 5、石斑魚 4、鱸魚子類 11（保留金目鱸／七星鱸分開）、烏魚 3、鰻魚 4。Phase AB 候選抽查各加 1/1/1/0/1/0 項來源觀察，但正式可檢索新增均為 0。\n\n"
report += "## 阻塞與後續門檻\n\n"
report += "1. 為每一資料集取得官方原始資源 bytes，記錄精確 resource/version/取得時間並計算 SHA-256。\n2. 對 114846 須固定完整 feed 版本及逐筆記錄，並限制索引範圍到明確 OGL 釋出的資料欄位；不得將 TFRI 外連網站全部內容視為 OGL。\n3. 對 18290 取得 ZIP 並驗證法規版本、生效日期、附件與廢止資訊後，才可建法律來源候選。\n4. 對 7274 取得可核驗資料並逐藥品確認適應症／養殖物種；欄位沒有停藥資訊時不得回答停藥期。\n5. 對 41845 找到資料 reference year / survey period，保留原始統計分類與單位；否則維持不適合產生年度數值題。\n6. 取得新來源的 owner admission decision 後，才能決定是否建入隔離的指定 Corpus。\n\n"
report += "Frozen baseline 本輪重查結果見 `compatibility.json` 更新欄位；正式 SQLite、Production、Phase AA 與歷史生成資料均未被本輪程式寫入。未執行 720 次評測；不產生專業準確率結論。\n"
(OUT / "phase_ab_final_report.md").write_text(report, encoding="utf-8")

print(json.dumps({"output": str(OUT), "staging": str(STAGE), "candidate_cards": len(records), "candidate_answers": len(ref_answers)}, ensure_ascii=False))
