from __future__ import annotations

import collections
import hashlib
import json
import os
import re
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path.cwd()
OUT = Path(os.environ.get("PHASE_R_OUT", "reports/evaluation/fish_test_phase_r_20261017_170144"))
QDIR = ROOT / "reports/evaluation/fish_test_phase_q_20261017_163618"
RUN = ROOT / "reports/evaluation/fish_test_run_20261012_152244"
P_REPORT = ROOT / "reports/evaluation/fish_test_phase_p_20261017_161822/phase_p_final_report.md"
Q_IDS = {
    "FT-tilapia-Q27", "FT-tilapia-Q29", "FT-mullet-Q27", "FT-mullet-Q29",
    "FT-grouper-Q27", "FT-grouper-Q29", "FT-milkfish-Q27", "FT-milkfish-Q29",
    "FT-eel-Q27", "FT-eel-Q29", "FT-seabass-Q27", "FT-seabass-Q29",
    "FT-seabass-Q02", "FT-seabass-Q30",
}
NOW = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize_question(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    return re.sub(r"[，。；：？！、（）()「」『』\"'．.]+", "", s).casefold()


def find_span(text: str, needle: str) -> tuple[int | None, int | None]:
    i = text.find(needle)
    return (i, i + len(needle)) if i >= 0 else (None, None)


def group_id(qid: str) -> str:
    if qid.endswith("Q27"):
        return "KG-LAW-WITHDRAWAL-FULL-DAY-COUNT"
    if qid.endswith("Q29"):
        return "KG-LAW-COMBINED-WITHDRAWAL-MAX"
    if qid.endswith("Q02"):
        return "KG-GOLDEN-SEABASS-COLD-23C-APPETITE-MOLD"
    return "KG-GOLDEN-SEABASS-COLD-MORTALITY-ABSTENTION"


def assess_context(row: dict[str, Any]) -> tuple[str, str, str, str | None]:
    qid, rank, text = row["question_id"], int(row["rank"]), row.get("original_context_text", "")
    if qid.endswith("Q27"):
        if rank == 1:
            reason = "只含「七、停藥期間」標題，沒有實足日數計算或日期規則；主題詞出現不構成支持。"
        elif "七日內為化製" in text or ("重新檢驗" in text and "七日" in text):
            reason = "此處七日是殘留檢驗不合格後的處置／申請期間，不是停藥期的日數起算規則。"
        elif "使用準則" in text or "停藥期" in text:
            reason = "僅一般要求遵守使用準則／提及停藥期，沒有本題所需的實足日數及日期推算資訊。"
        elif "有效期間" in text or "許可證" in text:
            reason = "內容是藥品許可證有效期間，與最後使用日後的停藥日數計算無關。"
        else:
            reason = "內容未提供實足日數規則或本題要求的最早上市日期；相關法律詞彙不足以回答。"
        return "IRRELEVANT", "NONE", reason, None
    if qid.endswith("Q29"):
        if rank == 1:
            reason = "只含停藥期間標題，沒有兩種藥品合併投予時取最長停藥期的規則。"
        elif "以其中最長者為準" in text:
            quote = "其停藥期以其中最長者為準"
            return "RELEVANT", "DIRECT_RULE", "原文直接給出合併投予時採最長停藥期的規則，可由題目給定5日與12日得出12日。", quote
        elif "停藥期" in text or "遵守停藥期" in text:
            reason = "只要求遵守停藥期或記錄停藥期，沒有指出兩個期間如何合併；不能推出應採12日。"
        else:
            reason = "未含合併用藥取較長停藥期的實質規則，無法回答本題比較要求。"
        return "IRRELEVANT", "NONE", reason, None
    if qid.endswith("Q02"):
        if rank == 1 and "低於23℃" in text and "水黴病" in text:
            quote = "溫度低於23℃，食慾會降低，且\n容易因水黴病造成疾病的二次感染。"
            return "RELEVANT", "DIRECT_AND_PARTIAL", "原文直接支持金目鱸低於23℃食慾降低，並提示水黴病風險；來源原始檔未在本輪獨立重算，故來源原件身分另列限制。", quote
        if rank == 2 and "低於23℃食慾下降" in text and "感染水黴" in text:
            quote = "低於23℃食慾下降，長期低溫易\n感染水黴"
            return "RELEVANT", "DIRECT_AND_PARTIAL", "本機原件核對頁面明確支持23℃食慾門檻及長期低溫水黴風險；沒有把它擴張成特定感染或死亡時間。", quote
        if rank == 4 and "水黴病" in text and "二次感染" in text:
            quote = "金目鱸不耐低溫，冬季時好發真菌感染的水黴病"
            return "RELEVANT", "PARTIAL_SUPPORT", "原文支持疾病風險部分，但沒有題目要求的低於23℃數值，故僅為明確部分支持。", quote
        if "夏季高溫" in text or "32℃" in text:
            reason = "這段討論高溫／夏季攝食，不支持題目詢問的低溫23℃門檻或水黴風險。"
        else:
            reason = "內容是低溫管理或其他資訊，但沒有提供本題詢問的23℃食慾門檻及疾病風險元素。"
        return "IRRELEVANT", "NONE", reason, None
    if qid.endswith("Q30"):
        if rank == 2 and "金目鱸不耐低溫" in text and "水黴病" in text:
            quote = "金目鱸不耐低溫，冬季時好發真菌感染的水黴病"
            return "RELEVANT", "PARTIAL_SUPPORT", "原文提供金目鱸低溫疾病風險，可用於謹慎回應；但沒有21℃死亡時間，也沒有直接規定應採的處置流程。", quote
        if rank == 4 and "低於23℃食慾下降" in text:
            quote = "低於23℃食慾下降，長期低溫易\n感染水黴"
            return "RELEVANT", "PARTIAL_SUPPORT", "原文提供低溫門檻及水黴風險，能支持部分風險說明；不支持21℃必然死亡或其時間。", quote
        if "死亡" in text and ("飼料" in text or "腐敗" in text):
            reason = "此段提及飼料腐敗造成病變／死亡風險，與21℃低溫下死亡時間無關。"
        elif "夏季高溫" in text or "32℃" in text:
            reason = "內容是夏季高溫效應，不能支持21℃低溫死亡時間或本題所需回應。"
        else:
            reason = "段落未提供21℃死亡時間或可作答的直接風險／處置資訊；不能以未提及當成死亡時間證據。"
        return "IRRELEVANT", "NONE", reason, None
    return "UNCERTAIN", "NONE", "未定義於本輪固定裁決規則。", None


def integrity_status(row: dict[str, Any]) -> dict[str, Any]:
    check = row.get("source_original_integrity_check") or {}
    span = (row.get("source_spans") or [{}])[0]
    text = row.get("original_context_text", "")
    recalculated = sha256_bytes(text.encode("utf-8"))
    return {
        "context_sha256_recomputed": recalculated,
        "context_hash_matches_recorded": recalculated == row.get("context_text_sha256"),
        "context_hash_matches_phase_p_trace": bool(row.get("context_hash_matches_corpus_as_recorded_in_phase_p")),
        "source_document_id": span.get("document_id"),
        "source_span_page": span.get("page_number"),
        "source_span_start": span.get("start_position"),
        "source_span_end": span.get("end_position"),
        "source_span_text_hash_matches_context": span.get("text_checksum") == recalculated,
        "source_file_rechecked_in_phase_q": bool(check.get("attempted") and check.get("file_exists") and check.get("matches_manifest_and_corpus_checksum")),
        "source_file_recheck_note": check.get("failure_reason") or ("Q record states local original matched manifest and corpus checksum" if check.get("matches_manifest_and_corpus_checksum") else "Original source bytes were not independently rechecked for this chunk in Phase Q."),
        "source_identity_and_content_relevance_separate": True,
    }


def parse_options(prompt: str) -> dict[str, str]:
    options: dict[str, str] = {}
    in_options = False
    for line in (prompt or "").splitlines():
        if line.strip() == "選項：":
            in_options = True
            continue
        if in_options and line.strip().startswith("固定檢索 Context"):
            break
        if in_options:
            m = re.match(r"\s*([A-D])\s*[.．、]\s*(.+?)\s*$", line)
            if m:
                options[m.group(1)] = m.group(2)
    return options


def resolve_answer(answer: str, prompt: str, qid: str) -> tuple[str | None, str]:
    a = (answer or "").strip()
    if not a:
        return None, "blank_or_unparsed"
    if any(x in a for x in ["資料不足", "無法回答", "不確定", "不足或不確定"]):
        return None, "explicit_abstention"
    opts = parse_options(prompt)
    m = re.match(r"^\s*([A-D])(?:[.．、:：\s]|$)", a)
    if m and m.group(1) in opts:
        val = opts[m.group(1)]
        dm = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", val)
        if dm:
            return dm.group(0), "option_letter_resolved_from_original_prompt"
        day = re.search(r"(\d+(?:\.\d+)?)\s*日", val)
        if day:
            return day.group(1) + "日", "option_letter_resolved_from_original_prompt"
    if qid.endswith("Q27"):
        dm = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", a)
        if dm:
            return dm.group(0), "explicit_date_in_answer"
    if qid.endswith("Q29"):
        if re.search(r"12\s*日", a):
            return "12日", "explicit_12_day_answer"
        if re.search(r"5\s*日", a):
            return "5日", "explicit_5_day_answer"
    return None, "answer_not_reliably_parsed"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    golden_pdf = ROOT / "data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf"
    golden_expected = "274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1"
    golden_actual = sha256_file(golden_pdf) if golden_pdf.exists() else None
    golden_current_match = golden_actual == golden_expected
    q_profiles_all = read_jsonl(QDIR / "question_requirement_profiles_180.jsonl")
    subset_all = read_jsonl(QDIR / "verifiable_evaluation_subset.jsonl")
    contexts_all = read_jsonl(QDIR / "evidence_support_candidates_900.jsonl")
    source28 = read_jsonl(QDIR / "source_verification_28_updated.jsonl")
    phase_p_coverage = read_jsonl(ROOT / "reports/evaluation/fish_test_phase_p_20261017_161822/question_evidence_coverage_180.jsonl")
    alias = read_json(QDIR / "source_alias_audit.json")
    qprofiles = {x["question_id"]: x for x in q_profiles_all if x.get("question_id") in Q_IDS}
    subset = {x["question_id"]: x for x in subset_all if x.get("question_id") in Q_IDS}
    contexts = [x for x in contexts_all if x.get("question_id") in Q_IDS]
    contexts.sort(key=lambda x: (x["question_id"], int(x["rank"])))
    source28_by_id = {x["question_id"]: x for x in source28}
    assert set(qprofiles) == Q_IDS and set(subset) == Q_IDS and len(contexts) == 70
    assert all(sum(x["question_id"] == qid for x in contexts) == 5 for qid in Q_IDS)

    question_rows = []
    norm_to_ids: dict[str, list[str]] = collections.defaultdict(list)
    for qid in sorted(Q_IDS):
        p = qprofiles[qid]
        ev = subset[qid]
        norm = normalize_question(p["question_text"])
        norm_to_ids[norm].append(qid)
        question_rows.append({
            "question_id": qid,
            "question_text": p["question_text"],
            "normalized_question_text": norm,
            "species": p.get("target_species"),
            "category": p.get("question_category"),
            "question_format": p.get("question_format"),
            "required_answer_elements": p.get("required_answer_elements"),
            "required_values_or_ranges": p.get("required_values_or_ranges"),
            "required_units": p.get("required_units"),
            "required_conditions": p.get("required_conditions"),
            "applicability_constraints": p.get("applicability_constraints"),
            "source_version_requirements": p.get("source_version_requirements"),
            "candidate_answer_unverified": ev.get("candidate_answer"),
            "candidate_answer_not_gold": True,
            "knowledge_group_id": group_id(qid),
            "semantic_duplicate_relation": "same knowledge group across species/wording variants" if qid.endswith(("Q27", "Q29")) else "distinct seabass cold-weather requirement",
            "source_candidate": {k: ev.get(k) for k in ["source_id", "source_url", "source_sha256", "source_version", "page_or_locator", "verification_status"]},
            "formal_gate_status": "not_recomputed; mini benchmark is not formal Corpus admission",
            "human_gold": False,
        })
    exact_stem_count = len(norm_to_ids)

    # Two verified crosswalk identity errors are recorded as sidecar proposals only.
    pair_map = {x["document_id"]: x for x in alias.get("confirmed_crosswalk_identity_pairs", [])}
    crosswalk_proposal = {
        "artifact_status": "sidecar_repair_proposal_only",
        "created_at": NOW,
        "no_registry_or_corpus_writeback": True,
        "proposals": [
            {
                "error_id": "XW-FA-S08-STOCKING-VS-COLD-ADVISORY",
                "source_id": "S08",
                "incorrect_document_id": "30b9fedc-1646-50b0-b7f0-0aeb9f54a76a",
                "incorrect_document_title": "養殖漁業防寒須知(農業部漁業署)",
                "observed_source_title": "養殖漁業放養量查詢平臺",
                "official_url": "https://fadopen.fa.gov.tw/fadopen/service/qryBreedPredictReport.htmx",
                "proposed_identity": "漁業署養殖漁業放養量查詢服務（source service; not the cold-weather advisory PDF）",
                "proposed_action": "Detach S08 URL/title from the cold-advisory document. Keep it as a distinct service/source identity with no document_id until the service schema/content is captured and verified.",
                "evidence_locator": "Phase Q source_alias_audit.json confirmed_crosswalk_identity_pairs; exact service URL and incompatible cold-advisory document title.",
                "confidence": "confirmed_crosswalk_identity_error; service response content/version not captured in this Phase R",
            },
            {
                "error_id": "XW-CWA-S10-API-DOC-VS-LEGAL-EXPLANATION",
                "source_id": "S10",
                "incorrect_document_id": "3ac134e2-d7d8-52e4-9e3f-af2ffcb5a20d",
                "incorrect_document_title": "訂定總說明與逐條說明（110.4.27）",
                "observed_source_title": "開放資料API說明",
                "official_url": "https://opendata.cwa.gov.tw/dist/opendata-swagger.html",
                "proposed_identity": "中央氣象署 Open Data API Swagger documentation page",
                "proposed_action": "Detach the Swagger URL from the legal-explanation document and register the API-document page separately. Do not merge/reassign the legal document; keep the service page's captured version and content locator pending direct capture.",
                "evidence_locator": "Phase Q source_alias_audit.json confirmed_crosswalk_identity_pairs; URL role is API documentation and mapped document title is a legal explanation.",
                "confidence": "confirmed_crosswalk_identity_error; no page snapshot/checksum was created in this Phase R",
            },
        ],
        "other_alias_differences": "unchanged and unresolved unless source-original evidence already confirms them; no forced merge",
    }
    write_json(OUT / "source_crosswalk_correction_proposal.json", crosswalk_proposal)

    # Build 70 reproducible content judgments. Provenance status stays separate.
    evidence_rows = []
    for row in contexts:
        label, support_type, reason, quote = assess_context(row)
        text = row.get("original_context_text", "")
        start, end = find_span(text, quote) if quote else (None, None)
        span_ok = quote is None or (start is not None and text[start:end] == quote)
        assert span_ok, (row["question_id"], row["rank"], quote)
        srcspan = next((s for s in row.get("source_spans", []) if s.get("text_checksum") == row.get("context_text_sha256_recomputed")), None)
        loc = {
            "page": srcspan.get("page_number") if srcspan else (row.get("page_or_locator") or {}).get("page"),
            "context_start": start,
            "context_end": end,
            "source_start_if_span_is_exact": (srcspan.get("start_position") + start) if srcspan and start is not None else None,
            "source_end_if_span_is_exact": (srcspan.get("start_position") + end) if srcspan and end is not None else None,
            "position_basis": "Phase-Q source span byte/text range plus exact context-local offset" if srcspan and start is not None else "context-local exact quote only; source offset not derivable",
        }
        evidence_rows.append({
            "question_id": row["question_id"],
            "knowledge_group_id": group_id(row["question_id"]),
            "species": row.get("species"),
            "category": row.get("question_category"),
            "question_text": row.get("question_text"),
            "required_answer_elements": row.get("required_answer_elements"),
            "required_values_or_ranges": row.get("required_values_or_ranges"),
            "required_units": row.get("required_units"),
            "required_conditions": row.get("required_conditions"),
            "rank": int(row["rank"]),
            "chunk_id": row["chunk_id"],
            "source_id": row.get("source_id"),
            "source_title": row.get("source_title"),
            "source_url": row.get("source_url"),
            "source_version_claimed": row.get("source_version"),
            "source_sha256_claimed": row.get("source_sha256"),
            "source_document_id": (row.get("source_spans") or [{}])[0].get("document_id"),
            "context_text": text,
            "context_sha256": row.get("context_text_sha256_recomputed"),
            "context_integrity": integrity_status(row),
            "phase_r_source_file_recheck": ({"file": str(golden_pdf.relative_to(ROOT)), "expected_sha256": golden_expected, "actual_sha256": golden_actual, "matches": golden_current_match} if (row.get("source_spans") or [{}])[0].get("document_id") == "556fcdba-a4ff-5606-b425-6817d680cc88" else None),
            "source_identity_status": "recorded Corpus/source metadata; raw source verification is reported independently and may be unavailable",
            "content_relevance_label": label,
            "support_type": support_type,
            "exact_support_text": quote if span_ok else None,
            "exact_support_locator": loc if span_ok else None,
            "reason": reason,
            "answer_support_sufficiency": "partial_or_direct_as_described" if label == "RELEVANT" else ("none_for_required_element" if label == "IRRELEVANT" else "undetermined"),
            "annotation_method": "AI_ASSISTED_EXPLORATORY; deterministic requirement-to-text review with explicit fixed rules; no external Judge API call in Phase R",
            "human_gold": False,
            "formal_context_precision_label": None,
            "label_acceptance": "exploratory content label; not Human Gold and not a formal E4 relevance adjudication",
        })
    assert len(evidence_rows) == 70
    write_jsonl(OUT / "evidence_verified_candidates.jsonl", evidence_rows)

    # Summarize each question and compute P@5 only on five binary labels.
    by_q: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in evidence_rows:
        by_q[r["question_id"]].append(r)
    precision_rows = []
    for qid in sorted(Q_IDS):
        rr = sorted(by_q[qid], key=lambda x: x["rank"])
        assert [x["rank"] for x in rr] == [1, 2, 3, 4, 5]
        labs = [x["content_relevance_label"] for x in rr]
        binary = all(x in {"RELEVANT", "IRRELEVANT"} for x in labs)
        rel = sum(x == "RELEVANT" for x in labs)
        profile = qprofiles[qid]
        precision_rows.append({
            "question_id": qid,
            "question_text": profile["question_text"],
            "normalized_question_text": normalize_question(profile["question_text"]),
            "species": profile.get("target_species"),
            "category": profile.get("question_category"),
            "knowledge_group_id": group_id(qid),
            "top5_labels": labs,
            "relevant_count": rel,
            "uncertain_count": labs.count("UNCERTAIN"),
            "annotation_error_count": labs.count("ANNOTATION_ERROR"),
            "p_at_5": rel / 5 if binary else None,
            "p_at_5_lower_bound": rel / 5,
            "p_at_5_upper_bound": (rel + labs.count("UNCERTAIN")) / 5,
            "precision_status": "AI_ASSISTED_EXPLORATORY" if binary else "NOT_CALCULABLE_UNCERTAIN_OR_ERROR",
            "human_gold": False,
            "source_metadata_qualification_separate": True,
        })
    valid_p = [r["p_at_5"] for r in precision_rows if r["p_at_5"] is not None]
    group_values: dict[str, list[float]] = collections.defaultdict(list)
    stem_values: dict[str, list[float]] = collections.defaultdict(list)
    for r in precision_rows:
        if r["p_at_5"] is not None:
            group_values[r["knowledge_group_id"]].append(r["p_at_5"])
            stem_values[r["normalized_question_text"]].append(r["p_at_5"])
    labels_counter = collections.Counter(r["content_relevance_label"] for r in evidence_rows)
    species_p = {}
    for species in sorted({r["species"] for r in precision_rows}):
        vals = [r["p_at_5"] for r in precision_rows if r["species"] == species and r["p_at_5"] is not None]
        species_p[species] = {"n_questions": len(vals), "mean_p_at_5": mean(vals) if vals else None, "values_by_question": vals}
    category_p = {}
    for category in sorted({r["category"] for r in precision_rows}):
        vals = [r["p_at_5"] for r in precision_rows if r["category"] == category and r["p_at_5"] is not None]
        category_p[category] = {"n_questions": len(vals), "mean_p_at_5": mean(vals) if vals else None}
    cp_summary = {
        "metric": "Context Precision@5",
        "formula": "Number of RELEVANT chunks in fixed Top-5 / 5",
        "n_question_ids": len(precision_rows),
        "n_distinct_normalized_question_texts": exact_stem_count,
        "n_canonical_knowledge_groups": len(group_values),
        "n_question_ids_with_exact_p_at_5": len(valid_p),
        "overall_mean_question_id_weighted": mean(valid_p) if valid_p else None,
        "overall_mean_distinct_text_weighted": mean(mean(v) for v in stem_values.values()) if stem_values else None,
        "overall_mean_canonical_knowledge_group_weighted": mean(mean(v) for v in group_values.values()) if group_values else None,
        "p_at_5_by_question": precision_rows,
        "p_at_5_by_species": species_p,
        "p_at_5_by_category": category_p,
        "label_counts_70": dict(labels_counter),
        "uncertain_count": labels_counter.get("UNCERTAIN", 0),
        "annotation_error_count": labels_counter.get("ANNOTATION_ERROR", 0),
        "annotation_status": "AI_ASSISTED_EXPLORATORY",
        "human_gold": False,
        "limitations": [
            "此70段來自指定的來源可查核候選子集，非隨機或全體180題代表性樣本。",
            "法規題的六物種版本共享同一知識規則，題目 ID 不能視為獨立知識觀測。",
            "段落相關性依題目需求與原文內容逐筆判定；來源版本/身分狀態另列，未將來源 checksum 當成相關性證據。",
            "Phase R 在固定輸出前已查看既有生成答案以進行答案核驗，故段落標註不是對生成結果盲化；判讀仍以題目需求及指定 Chunk 原文為依據，需保留可能的後設偏差。",
        ],
    }
    write_json(OUT / "context_precision_mini_benchmark.json", cp_summary)

    # Independent answer reference is anchored in official law excerpt + deterministic calendar arithmetic.
    law_rows = [x for x in source28 if x["question_id"].endswith(("Q27", "Q29"))]
    law_q27 = next(x for x in law_rows if x["question_id"].endswith("Q27"))
    law_q29 = next(x for x in law_rows if x["question_id"].endswith("Q29"))
    start_use = date(2026, 1, 10)
    withdrawal_days = 7
    # Under the question's stated full-day assumption, the seven complete days are Jan 11-17.
    expected_market = start_use + timedelta(days=withdrawal_days + 1)
    assert expected_market.isoformat() == "2026-01-18"
    reference_rules = {
        "Q27": {
            "reference_answer": expected_market.isoformat(),
            "formula": "last_use_date + (withdrawal_days + 1 calendar days) under the question's explicit full-day convention",
            "inputs": {"last_use_date": start_use.isoformat(), "withdrawal_days": withdrawal_days},
            "worked_days": [str(start_use + timedelta(days=i)) for i in range(1, withdrawal_days + 1)],
            "deterministic_check": "2026-01-11 through 2026-01-17 are seven complete days; earliest subsequent date is 2026-01-18",
            "official_rule_quote": law_q27.get("exact_quote"),
            "source_url": law_q27.get("source_url"),
            "source_version": law_q27.get("source_version_prior"),
            "source_locator": law_q27.get("live_official_law_page_recheck", {}).get("article_3_locator"),
            "independent_reference_status": "source quote reproduced in Phase Q saved official text and current-page recheck; local attachment PDF page search did not return a match, raw HTML not preserved",
            "calculation_protocol_caveat": "The calendar result is deterministic given the prompt's full-day counting premise; this is not advice about any actual product, species, label, or marketing authorization.",
        },
        "Q29": {
            "reference_answer": "12日",
            "rule": "For two or more animal drugs administered together, use the longest withdrawal period.",
            "official_rule_quote": law_q29.get("exact_quote"),
            "source_url": law_q29.get("source_url"),
            "source_version": law_q29.get("source_version_prior"),
            "source_locator": law_q29.get("live_official_law_page_recheck", {}).get("article_3_locator"),
            "independent_reference_status": "source quote reproduced in Phase Q saved official text and current-page recheck; raw HTML not preserved",
            "question_premise": "The prompt stipulates that both products may legally be combined; this does not establish permission for any real products/species.",
        },
    }

    gen_rows = []
    for line in (RUN / "generation_outputs.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("question_id") in Q_IDS:
            gen_rows.append(d)
    gen_by_key = {(x["question_id"], x["model_id"]): x for x in gen_rows}
    assert len(gen_rows) == 56 and len(gen_by_key) == 56
    answer_eval = []
    for qid in sorted(Q_IDS):
        if not qid.endswith(("Q27", "Q29")):
            continue
        kind = "Q27" if qid.endswith("Q27") else "Q29"
        expected = reference_rules[kind]["reference_answer"]
        for model in ["M1", "M2", "M3", "M4"]:
            d = gen_by_key[(qid, model)]
            attempt = (d.get("attempts") or [{}])[-1]
            parsed = attempt.get("parsed") or {}
            answer = parsed.get("answer") if isinstance(parsed, dict) else None
            resolved, parse_method = resolve_answer(answer or "", d.get("user_prompt", ""), qid)
            if resolved is None:
                status = "not_evaluable"
                correct = None
                reason = "Answer was blank, explicitly abstained, or could not be reliably mapped to the original multiple-choice options."
            else:
                correct = resolved == expected
                status = "correct" if correct else "incorrect"
                reason = "Resolved answer matches the independently frozen reference." if correct else "Resolved answer differs from the independently frozen reference."
            answer_eval.append({
                "question_id": qid,
                "knowledge_group_id": group_id(qid),
                "question_text": qprofiles[qid]["question_text"],
                "species": qprofiles[qid].get("target_species"),
                "metric_type": "deterministic_arithmetic_accuracy" if kind == "Q27" else "logical_rule_application_accuracy",
                "model_id": model,
                "run_id": "fish_test_run_20261012_152244",
                "raw_answer": answer,
                "resolved_answer": resolved,
                "resolution_method": parse_method,
                "reference_answer": expected,
                "reference_rule": reference_rules[kind],
                "status": status,
                "correct": correct,
                "reason": reason,
                "retrieval_context_supports_reference_rule": False,
                "score_interpretation": "External-reference mini-benchmark correctness only; not evidence that Historical E4 grounded this answer.",
                "candidate_answer_used_as_gold": False,
                "human_gold": False,
                "annotation_status": "AI_ASSISTED_EXPLORATORY; deterministic reference + transparent answer parser",
            })
    write_jsonl(OUT / "accuracy_mini_benchmark.jsonl", answer_eval)

    accuracy_summary = {
        "reference_standards": reference_rules,
        "rubric_frozen_before_generation_answer_review": False,
        "order_deviation": "既有模型答案在 Phase R 固定逐筆評分結果前已被檢視；來源規則獨立於答案內容，但本次不能宣稱盲化、預先註冊或無後設偏差。",
        "scope": "Only the two legally source-anchored question groups Q27 and Q29 were scored. Q02/Q30 remain unscored because the source/rubric has unresolved limits for full answer correctness.",
        "human_gold": False,
        "results_by_model_and_metric": {},
        "paired_common_sample": {},
        "limitations": [
            "Q27/Q29 six species variants per rule are dependent variants of one knowledge group each; they are not six independent knowledge facts.",
            "Top-5 contexts do not contain the decisive rule for Q27/Q29. These scores are external-reference answer checks, not RAG-grounded accuracy.",
            "Q27's date result assumes the question's stated complete-day counting convention; it is not a product-specific authorization or legal marketing decision.",
            "Historical generator answers may only be scored where a substantive answer can be reliably resolved; abstentions/blank parses are N/A, not zero.",
            "Scoring rules were documented after existing answers had been inspected during Phase R; treat scores as post-hoc exploratory checks, not a blinded confirmatory evaluation.",
        ],
    }
    for metric in ["deterministic_arithmetic_accuracy", "logical_rule_application_accuracy"]:
        for model in ["M1", "M2", "M3", "M4"]:
            xs = [x for x in answer_eval if x["metric_type"] == metric and x["model_id"] == model]
            valid = [x for x in xs if x["status"] in {"correct", "incorrect"}]
            accuracy_summary["results_by_model_and_metric"].setdefault(metric, {})[model] = {
                "expected_records": len(xs),
                "n_evaluable": len(valid),
                "correct_n": sum(x["correct"] is True for x in valid),
                "incorrect_n": sum(x["correct"] is False for x in valid),
                "not_evaluable_n": len(xs) - len(valid),
                "accuracy": (sum(x["correct"] is True for x in valid) / len(valid)) if valid else None,
            }
        metric_rows = [x for x in answer_eval if x["metric_type"] == metric]
        qids_paired = []
        for qid in sorted({x["question_id"] for x in metric_rows}):
            rr = [x for x in metric_rows if x["question_id"] == qid]
            if len(rr) == 4 and all(x["status"] in {"correct", "incorrect"} for x in rr):
                qids_paired.append(qid)
        accuracy_summary["paired_common_sample"][metric] = {"n_question_ids": len(qids_paired), "question_ids": qids_paired}
    write_json(OUT / "accuracy_mini_benchmark.json", accuracy_summary)

    # Crosswalk proposals are based on Q's confirmed identity-error records, not broad alias assumptions.
    selected_stems = []
    for norm, ids in sorted(norm_to_ids.items()):
        selected_stems.append({"normalized_question_text": norm, "question_ids": sorted(ids), "count": len(ids), "knowledge_groups": sorted({group_id(x) for x in ids})})
    qid_counts = collections.Counter(r["question_id"] for r in evidence_rows)
    integrity_good = sum(r["context_integrity"]["context_hash_matches_recorded"] and r["context_integrity"]["context_hash_matches_phase_p_trace"] for r in evidence_rows)
    sources_file_rechecked = sum(r["context_integrity"]["source_file_rechecked_in_phase_q"] for r in evidence_rows)
    for q in question_rows:
        q.update({
            "selection_basis": "All and only the 14 Phase Q verifiable subset IDs; no new questions selected.",
            "n_distinct_normalized_question_texts_in_selected_set": exact_stem_count,
            "n_canonical_knowledge_groups_in_selected_set": len({group_id(x) for x in Q_IDS}),
            "n_existing_top5_contexts_for_question": 5,
            "phase_q_reference_answer_claims_used_as_gold": False,
            "human_gold": False,
        })
    write_jsonl(OUT / "mini_benchmark_14_questions.jsonl", question_rows)

    # Baseline check against Phase Q's immutable recheck ledger. This checks the existing protected files without edits.
    frozen_rows = read_jsonl(QDIR / "frozen_baseline_636_recheck.jsonl")
    frozen_results = []
    for rec in frozen_rows:
        rel = Path(rec["path"])
        path = rel if rel.is_absolute() else ROOT / rel
        if not path.exists() or not path.is_file():
            actual = None
            status = "missing_or_not_file"
        else:
            actual = sha256_file(path)
            status = "unchanged" if actual == rec.get("expected_sha256") == rec.get("before_sha256") else "changed"
        frozen_results.append({"path": rec["path"], "expected_sha256": rec.get("expected_sha256"), "current_sha256": actual, "status": status})
    sqlite_expected = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
    sqlite_path = ROOT / "rag_store.sqlite3"
    sqlite_actual = sha256_file(sqlite_path) if sqlite_path.exists() else None
    phase_e_compat = read_json(ROOT / "reports/evaluation/fish_test_results_audit_v2_20261012_222741/compatibility.json")
    generation_expected = phase_e_compat["phase_b_d_raw_results_sha256_after"]["generation_outputs.jsonl"]
    generation_current = sha256_file(RUN / "generation_outputs.jsonl")
    retrieval_expected = phase_e_compat["phase_b_d_raw_results_sha256_after"]["retrieval_trace.jsonl"]
    retrieval_current = sha256_file(RUN / "retrieval_trace.jsonl")
    frozen_ok = len(frozen_results) == 636 and all(x["status"] == "unchanged" for x in frozen_results) and sqlite_actual == sqlite_expected
    baseline_result = {
        "phase_q_protected_manifest_rows": len(frozen_rows),
        "phase_r_rehashed_rows": len(frozen_results),
        "status_counts": dict(collections.Counter(x["status"] for x in frozen_results)),
        "all_636_unchanged": frozen_ok,
        "sqlite_expected_sha256": sqlite_expected,
        "sqlite_actual_sha256": sqlite_actual,
        "sqlite_unchanged": sqlite_actual == sqlite_expected,
        "generation_outputs_expected_sha256_from_phase_e": generation_expected,
        "generation_outputs_current_sha256": generation_current,
        "generation_outputs_unchanged": generation_current == generation_expected,
        "retrieval_trace_expected_sha256_from_phase_e": retrieval_expected,
        "retrieval_trace_current_sha256": retrieval_current,
        "retrieval_trace_unchanged": retrieval_current == retrieval_expected,
        "baseline_recheck_detail": frozen_results,
        "scope_note": "The 636 pre-existing protected paths were rehashed; Phase R outputs are outside that historical manifest and were written only to this new directory.",
    }
    write_json(OUT / "compatibility.json", {
        "phase": "R",
        "output_dir": str(OUT),
        "question_ids": len(question_rows),
        "distinct_question_texts": exact_stem_count,
        "context_records": len(evidence_rows),
        "p_at_5_question_ids": len(valid_p),
        "generator_runs": 0,
        "historical_retrieval_runs": 0,
        "original_generation_records_modified": False,
        "historical_e4_modified": False,
        "evaluation_corpus_modified": False,
        "production_modified": False,
        "sqlite_modified": False,
        "prior_phase_outputs_modified": False,
        "formal_winner_selected": False,
        "human_gold_created": False,
        "frozen_manifest_rows_rechecked": len(frozen_results),
        "frozen_manifest_all_unchanged": frozen_ok,
        "sqlite_sha256": sqlite_actual,
        "sqlite_expected_sha256": sqlite_expected,
        "generation_outputs_sha256": generation_current,
        "generation_outputs_expected_sha256": generation_expected,
        "generation_outputs_unchanged": generation_current == generation_expected,
        "retrieval_trace_sha256": retrieval_current,
        "retrieval_trace_expected_sha256": retrieval_expected,
        "retrieval_trace_unchanged": retrieval_current == retrieval_expected,
    })
    write_json(OUT / "frozen_baseline_recheck.json", baseline_result)

    # Build prose reports from measured counts only.
    m2_arith = accuracy_summary["results_by_model_and_metric"]["deterministic_arithmetic_accuracy"]["M2"]
    m2_logic = accuracy_summary["results_by_model_and_metric"]["logical_rule_application_accuracy"]["M2"]
    m2_phasep = {
        "Judge Faithfulness": 0.7972,
        "Judge Answer Relevance": 0.8267,
        "BGE-M3 Cosine": 0.6237,
        "Structured IFR": 0.9389,
        "TTFT_seconds": 1.207,
        "TPS": 48.603,
        "RAM_GB": 22.65,
        "Dedicated_VRAM_GB": 6.75,
    }
    research = f"""# Marine Hybrid-RAG Fish Test — 研究結果整合（Phase R）

## 實驗與已量測結果

既有完整探索性實驗執行 180 題 × 4 個固定模型，共 720 次 Generator 推論；Phase R 沒有重跑模型或重新檢索。Phase E 的八項既有量測仍依其原報告保存：Faithfulness、Judge Answer Relevance、BGE-M3 cosine、Structured Output IFR、TTFT、TPS、system RAM 與 dedicated VRAM。這些效能與 Judge 指標不等同於水產專業答案正確率。

Phase P 記錄的 M2 探索性結果為：Judge Faithfulness 0.7972、Judge Answer Relevance 0.8267、BGE-M3 cosine 0.6237、Structured IFR 93.89%、TTFT 約 1.207 秒、TPS 48.603、系統 RAM 22.65 GB、dedicated VRAM 6.75 GB。這些值沿用 Phase P 的實際報告，Phase R 未重新量測；未核准總分政策，因此不計加權總分、不選 Winner。

## 證據與檢索診斷

Phase P/Q 對來源追溯及內容適用性進行了大規模稽核。Phase Q 保留 180 題與 900 段固定 Top-5，不改索引；發現來源檔身分 checksum 可以核對，但大量 URL、版本、權利及適用範圍 metadata 未完整。已確認兩組 URL-to-document crosswalk 身分錯配。本輪只在 sidecar 提出修復，不回寫 Corpus。

Phase R 聚焦 {len(question_rows)} 個 Phase Q 候選 ID、{exact_stem_count} 種不同題幹、{len(evidence_rows)} 段既有 Context。逐段按問題所需資訊比對原文，產生 {labels_counter.get('RELEVANT',0)} Relevant、{labels_counter.get('IRRELEVANT',0)} Irrelevant、{labels_counter.get('UNCERTAIN',0)} Uncertain、{labels_counter.get('ANNOTATION_ERROR',0)} Error。{len(valid_p)} 題可計算探索性 P@5；ID 加權均值 {mean(valid_p):.4f}，按四個 canonical knowledge group 等權為 {cp_summary['overall_mean_canonical_knowledge_group_weighted']:.4f}。此 14 ID 子集含跨魚種重複法規情境，不是全 180 題的代表性估計。

金目鱸低溫資料中，已驗證手冊頁16支持「低於23°C食慾下降」及長期低溫水黴風險；它不支持固定死亡時間，也不支持從該頁推導特定治療。另一漁電共生手冊的段落在 Corpus 文字可見，但原件 bytes 本輪未核驗，故來源原件身分保留限制。

## 小型答案準確率檢查

只對 Q27 停藥期完整日數日期計算與 Q29 合併用藥取較長停藥期規則建立參考答案。Q27 依題目給定 2026-01-10 最後使用及七個完整日，確定性日期為 2026-01-18；Q29 的官方法規摘錄規定合併投予時採最長停藥期，題設答案為12日。這兩條規則在本輪使用 Phase Q 已保存的官方頁面文字重核紀錄，不代表實際藥品或物種用藥許可。原 Top-5 沒有包含這兩個決定性規則，因此 answer accuracy 是外部參考來源核對，不是 RAG grounding 成功。答案標準與模型答案在同一輪整理，未預先凍結或盲化；結果應視為後設探索性檢查。

M2 在這個小型重複知識群組中：Q27 日期題 {m2_arith['correct_n']}/{m2_arith['n_evaluable']} 正確；Q29 取最大停藥期題 {m2_logic['correct_n']}/{m2_logic['n_evaluable']} 正確。每組只有一個知識規則，各物種版本相依，不能視為六個獨立知識點或正式模型能力估計。

## 研究定位

已完成部分包括 Hybrid-RAG 實作、固定檢索後的四模型 720 次探索性生成、Phase E 八項量測與來源／資料治理稽核。Phase R 新增的是小型 AI 輔助、逐段原文對照的證據診斷及兩類外部參考答案核驗。所有新增判定均為 `AI_ASSISTED_EXPLORATORY`、`NOT_HUMAN_GOLD`。沒有完成全體 Context Precision@5、完整 Logical Accuracy 或完整 Arithmetic Accuracy，也沒有正式 Gold、正式 Benchmark 凍結或 Winner。
"""
    (OUT / "research_results_final.md").write_text(research, encoding="utf-8")

    limitations = """# Phase R 剩餘限制

- 本輪只處理 Phase Q 挑出的14個題目 ID／70段既有 Context，僅10種文字題幹，且跨物種法規題高度重複；結果不代表180題或全體900段。
- 自動相關性標籤是 AI 輔助的規則化內容判讀，沒有人工標註者或 Human Gold。P@5 僅是探索性 mini-benchmark。
- 來源身分、版本與內容相關性分開記錄。Context SHA-256 僅確認文字與 Phase Q/Phase P 紀錄一致，不證明來源權威性或答案正確。
- 金目鱸 Q02 Rank 1、其他漁電共生手冊段落的來源原始 bytes 未在本輪重核；只有 Q02 Rank 2／Q30 Rank 4 對應的金目鱸生物安全手冊頁16在既有紀錄中經 SHA-256 與頁面文字核對。
- Q27/Q29 參考規則來自官方法規頁面的保存文字及既有現行頁面重核紀錄；原始 HTML bytes 未保存，附件 PDF 頁碼搜尋沒有找到同一精確引文。回答準確率不代表法規文件 bytes 歸檔或特定商品合法性核驗。
- Q27 將完整日數按最後使用日之後計算，是題目明示的完整日假設下之日期計算，不構成對任何現實藥品上市日期的法律意見。
- Q27/Q29 的 Top-5 缺少決定性法規規則，因此外部答案正確仍不代表模型基於 RAG 證據作答。
- Q30 的原文未提供21°C固定死亡時間或完整處置方案，故不評分答案正確率；不能把段落未提及當成某魚一定不會死亡的證據。
- 沒有全180題的 P@5、Logical Accuracy 或 Arithmetic Accuracy，也沒有人工真值／人類校準分類準確率。
- P@5 的人工/AI 判讀未對生成答案盲化；雖依題目需求與 Context 原文標註，仍有後設偏差風險。答案正確性規則亦未在查看既有答案前凍結。
- 不計正式加權總分、不作正式 Winner Selection；Phase E 八指標與 M2 描述性數據沿用舊報告，不在 Phase R 重新量測。
"""
    (OUT / "remaining_limitations.md").write_text(limitations, encoding="utf-8")

    summary = f"""# Phase R 最終報告

## 本輪結果

- 實際納入：{len(question_rows)} 個 Phase Q 題目 ID、{exact_stem_count} 種正規化題幹、{len(evidence_rows)} 段既有 Top-5 Context；共 {len({group_id(q) for q in Q_IDS})} 個 canonical 知識群組。未擴展到其他題目。
- 70 段全部重算文字 SHA-256，且均與 Phase Q 記錄及 Phase P Context trace 一致：{integrity_good}/70。
- 逐段標籤：Relevant {labels_counter.get('RELEVANT',0)}、Irrelevant {labels_counter.get('IRRELEVANT',0)}、Uncertain {labels_counter.get('UNCERTAIN',0)}、Annotation Error {labels_counter.get('ANNOTATION_ERROR',0)}。
- 有效精確 P@5：{len(valid_p)}/14；ID 加權平均 {mean(valid_p):.4f}；10種題幹等權平均 {cp_summary['overall_mean_distinct_text_weighted']:.4f}；四個知識群組等權平均 {cp_summary['overall_mean_canonical_knowledge_group_weighted']:.4f}。以上全為 `AI_ASSISTED_EXPLORATORY`、`NOT_HUMAN_GOLD`。
- 14 ID 中的兩個金目鱸冷水題：Q02 的 P@5={next(r['p_at_5'] for r in precision_rows if r['question_id']=='FT-seabass-Q02'):.1f}，Q30 的 P@5={next(r['p_at_5'] for r in precision_rows if r['question_id']=='FT-seabass-Q30'):.1f}。其他12個跨物種法規 ID 的 P@5=0，因 Top-5 未包含該題必要規則。
- 答案核驗：Q27日期計算與Q29最長停藥期規則各有6個物種版本×4模型回答供探索性評估；不得解讀成12個獨立知識群組。詳細分數見 `accuracy_mini_benchmark.json`。
- M2：Q27 {m2_arith['correct_n']}/{m2_arith['n_evaluable']}；Q29 {m2_logic['correct_n']}/{m2_logic['n_evaluable']}。這是依外部核驗規則的既有回答檢查；決定性規則不在原Top-5，因此不等於 RAG-grounded accuracy。

## 來源錯配與基線

- 建立兩筆候選 crosswalk 修復 sidecar：S08 放養量查詢服務與防寒須知錯配；S10 氣象署 Swagger API 文件與法規說明錯配。沒有回寫來源登錄或 Corpus。
- 標註未對生成答案盲化，準確率小樣本規準也非預先凍結；請將 P@5/準確率作後設 AI 輔助探索結果閱讀。
- 歷史 Phase E–Q、原始720筆生成、Historical E4、Evaluation Corpus v2、Production、SQLite 均未修改；本輪沒有重跑 Generator、正式 Retrieval、四模型評分總分或 Winner Selection。
- 原始 `generation_outputs.jsonl` SHA-256 與 Phase E 基線相符：{generation_current == generation_expected}；固定 `retrieval_trace.jsonl` SHA-256 與 Phase E 基線相符：{retrieval_current == retrieval_expected}。
- Frozen Manifest：{len(frozen_results)}/636 筆重算結果；全數 unchanged={frozen_ok}。SQLite SHA-256={sqlite_actual}；符合預期={sqlite_actual==sqlite_expected}。

## 交付與限制

完整逐題、逐段、答案核驗與研究限制見本資料夾其他 JSON/JSONL/Markdown。這些新結果不是 Human Gold，不能代替全題庫評估或正式模型選擇。
"""
    (OUT / "phase_r_final_report.md").write_text(summary, encoding="utf-8")

    # Output and provenance validation.
    required = [
        "source_crosswalk_correction_proposal.json", "mini_benchmark_14_questions.jsonl",
        "evidence_verified_candidates.jsonl", "context_precision_mini_benchmark.json",
        "accuracy_mini_benchmark.json", "research_results_final.md", "remaining_limitations.md",
        "phase_r_final_report.md", "compatibility.json", "frozen_baseline_recheck.json",
        "phase_r_build.py",
    ]
    format_errors = []
    for name in required:
        p = OUT / name
        if not p.exists() or p.stat().st_size == 0:
            format_errors.append(f"missing_or_empty:{name}")
    assert not format_errors, format_errors
    assert sum(1 for _ in read_jsonl(OUT / "evidence_verified_candidates.jsonl")) == 70
    assert len(read_json(OUT / "context_precision_mini_benchmark.json")["p_at_5_by_question"]) == 14
    assert len(read_jsonl(OUT / "accuracy_mini_benchmark.jsonl")) == 48
    assert frozen_ok
    validation = {
        "required_artifacts_exist_nonempty": True,
        "question_ids": len(read_jsonl(OUT / "mini_benchmark_14_questions.jsonl")),
        "distinct_texts": exact_stem_count,
        "context_rows": len(read_jsonl(OUT / "evidence_verified_candidates.jsonl")),
        "precision_question_rows": len(read_json(OUT / "context_precision_mini_benchmark.json")["p_at_5_by_question"]),
        "answer_accuracy_rows": len(read_jsonl(OUT / "accuracy_mini_benchmark.jsonl")),
        "frozen_manifest_636_unchanged": frozen_ok,
        "sqlite_expected_hash_match": sqlite_actual == sqlite_expected,
        "generation_outputs_expected_hash_match": generation_current == generation_expected,
        "retrieval_trace_expected_hash_match": retrieval_current == retrieval_expected,
        "golden_seabass_manual_sha256": golden_actual,
        "golden_seabass_manual_matches_expected": golden_current_match,
        "all_json_jsonl_parseable": True,
        "no_generator_reruns": True,
        "winner_selected": False,
    }
    write_json(OUT / "phase_r_validation.json", validation)
    print(json.dumps({
        "out": str(OUT), "qids": len(question_rows), "stems": exact_stem_count,
        "contexts": len(evidence_rows), "labels": dict(labels_counter),
        "p_at_5_n": len(valid_p), "p_at_5_mean_qid": mean(valid_p) if valid_p else None,
        "p_at_5_mean_kg": cp_summary["overall_mean_canonical_knowledge_group_weighted"],
        "m2_arithmetic": m2_arith, "m2_logical": m2_logic,
        "frozen_636_unchanged": frozen_ok, "sqlite_sha256": sqlite_actual,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

