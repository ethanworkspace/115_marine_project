from __future__ import annotations

import collections
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DB = WORK / "corpus" / "marine_hybrid_rag_corpus_v3.sqlite3"
QUESTION_FILE = ROOT / "reports" / "evaluation" / "fish_test_phase_a_20261012" / "fish_test_questions_normalized.jsonl"
AA_REFS = ROOT / "reports" / "evaluation" / "fish_test_phase_aa_20261019_220906" / "reference_answers_frozen.jsonl"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
RERANKER_PATH = ROOT / ".venv-reranker" / "hf-cache" / "hub" / "models--BAAI--bge-reranker-v2-m3" / "snapshots" / "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
STAT_TERMS = ["面積", "統計", "縣市", "數量", "總計", "公頃", "2020", "民國109", "109年", "主計總處"]
MEDICATION_RISK_TERMS = ["劑量", "用量", "幾次", "頻率", "停藥", "休藥", "withdrawal", "dosage", "使用幾天"]
VALUE_CUES = ["多少", "幾", "範圍", "水溫", "適溫", "密度", "數值", "單位", "比例", "百分", "公頃", "mg", "℃", "°C", "天數", "年齡", "幾日", "多少尾", "幾尾", "FCR", "SGR"]
CONDITION_CUES = ["低於", "高於", "以上", "以下", "最適", "第一年", "第一齡", "1齡", "2齡", "以上", "期間", "時", "若", "需", "條件"]
STOP = {"請問", "如何", "什麼", "為何", "哪個", "哪些", "依據", "資料", "原文", "問題", "說明", "回答", "魚類", "養殖", "請", "是否", "以及", "還有", "並且"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cjk_tokens(text: str) -> list[str]:
    text = str(text or "").lower()
    result: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) == 1:
            result.append(run)
        else:
            result.extend(run[i:i + 2] for i in range(len(run) - 1))
    result.extend(re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", text))
    return list(dict.fromkeys(result))


def meaningful_tokens(text: str) -> set[str]:
    return {t for t in cjk_tokens(text) if t not in STOP and not any(s in t for s in SPECIES)}


def jaccard(a: str, b: str) -> float:
    aa, bb = meaningful_tokens(a), meaningful_tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def _embed(texts: list[str]) -> list[np.ndarray]:
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    row = next((x for x in tags if x.get("name") == EMBED_MODEL), None)
    if not row or str(row.get("digest", "")).removeprefix("sha256:") != EMBED_DIGEST:
        raise RuntimeError("BGE-M3 model digest mismatch")
    output = []
    for start in range(0, len(texts), 16):
        batch = texts[start:start+16]
        response = requests.post("http://127.0.0.1:11434/api/embed", json={"model": EMBED_MODEL, "input": batch, "truncate": True}, timeout=240)
        response.raise_for_status()
        vectors = response.json().get("embeddings", [])
        if len(vectors) != len(batch):
            raise RuntimeError(f"query embedding batch count mismatch: {len(vectors)}/{len(batch)}")
        for vector in vectors:
            arr = np.asarray(vector, dtype=np.float32)
            if arr.shape != (1024,) or not np.isfinite(arr).all():
                raise RuntimeError(f"invalid query embedding shape/value: {arr.shape}")
            norm = float(np.linalg.norm(arr))
            if norm <= 0:
                raise RuntimeError("zero query vector")
            output.append(arr/norm)
    return output


def load_reranker():
    for site in (ROOT / ".venv-reranker" / "Lib" / "site-packages", ROOT / ".venv" / "Lib" / "site-packages"):
        if site.exists() and str(site) not in sys.path:
            sys.path.insert(0, str(site.resolve()))
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoderRuntime(RERANKER_PATH, device=device, max_length=512, batch_size=8)


def load_chunks() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("SELECT * FROM chunks WHERE retrieval_eligible=1 ORDER BY chunk_id"):
        item = dict(r)
        item["embedding_array"] = np.frombuffer(item["embedding"], dtype=np.float32)
        item["species_scope_list"] = [x for x in str(item["species_scope"]).split("|") if x]
        item["category_scope_list"] = json.loads(item["category_scope"])
        item["restrictions"] = json.loads(item["restrictions_json"])
        rows.append(item)
    recs = {}
    for r in con.execute("SELECT source_record_id,source_id,original_record_json,source_record_locator,duplicate_group_id FROM source_records"):
        recs[r["source_record_id"]] = {**dict(r), "original_record_json": json.loads(r["original_record_json"])}
    sources = [dict(r) for r in con.execute("SELECT * FROM sources")]
    con.close()
    return rows, recs, sources


def make_requirement_profile(q: dict[str, Any]) -> dict[str, Any]:
    text = q["question_text"]
    species = q["species_chinese"]
    value_needed = any(cue.lower() in text.lower() for cue in VALUE_CUES)
    conditions = [cue for cue in CONDITION_CUES if cue in text]
    source_version = "law/date/version required" if any(x in text for x in ["法規", "法令", "許可", "停藥", "藥品", "生效", "條文"]) else "source version required if source is time-sensitive"
    required = ["topic_answer"]
    if value_needed:
        required.append("requested_value_or_range_if_question_requests_one")
    if conditions:
        required.append("explicit_condition:" + ",".join(conditions))
    units = [u for u in ["°C", "℃", "mg/L", "公頃", "尾", "%", "日", "天", "年"] if u in text]
    return {
        "question_id": q["question_id"], "target_species": species, "question_category": q.get("inferred_category"),
        "category_basis": q.get("category_basis"), "required_answer_elements": required,
        "required_values_or_ranges": "required" if value_needed else "not_explicitly_requested",
        "required_units": units, "required_conditions": conditions,
        "applicability_constraints": {"target_species_label_from_original_workbook": species, "no_taxonomic_alias_expansion": True},
        "source_version_requirements": source_version, "profile_method": "rule-based parse of question text only; candidate answer and generator outputs not consulted",
        "profile_status": "AUTO_REQUIREMENT_PROFILE_NOT_HUMAN_GOLD", "original_question": text,
    }


def fts_bm25(con: sqlite3.Connection, query: str, limit: int = 40) -> list[dict[str, Any]]:
    terms = cjk_tokens(query)
    if not terms:
        return []
    terms = terms[:48]
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    sql = """SELECT c.chunk_id, bm25(chunks_fts) AS bm25_raw
             FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id
             WHERE chunks_fts MATCH ? ORDER BY bm25_raw ASC, c.chunk_id ASC LIMIT ?"""
    try:
        values = con.execute(sql, (match, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"chunk_id": r[0], "bm25_score": float(-r[1])} for r in values]


def source_applicability(row: dict[str, Any], profile: dict[str, Any], record: dict[str, Any]) -> tuple[bool, str]:
    question = profile["original_question"]
    source_id = row["source_id"]
    if source_id == "DGBAS-79395-2020":
        text = row["text"]
        stat_intent = any(t in question for t in STAT_TERMS)
        record_payload = record["original_record_json"]
        native_category = str(record_payload.get("original_category_label", ""))
        category_match = native_category and native_category.rstrip("類") in question
        if stat_intent and category_match and ("2020" in question or "109" in question):
            return True, "DGBAS_NATIVE_CATEGORY_STATISTIC_QUERY_ONLY"
        return False, "DGBAS_STAT_CATEGORY_NOT_FISH_SPECIES_ADVICE_OR_QUERY_NOT_EXPLICITLY_STATISTICAL"
    if source_id == "MOA-EEL-STOCKING-OPEN-41845":
        return False, "CONTEXT_ONLY_NO_REFERENCE_YEAR"
    target = str(profile["target_species"])
    scopes = row["species_scope_list"]
    # Source-located taxonomic exceptions found in the full content review.
    # These do not mutate the now-frozen SQLite/embedding snapshot.
    if source_id == "MOA-TFRI-OPEN-114846":
        record_no = int(row["chunk_id"].split("-")[2])
        reviewed_other_taxa = {257:"虎皮蛙",414:"黃臘鰺 Trachinotus",424:"虎皮蛙／牛蛙",470:"鯽魚",477:"鯽魚",495:"田螺／明潭吻鰕虎",529:"蜆",928:"筍殼魚",956:"錦鯉"}
        if record_no in reviewed_other_taxa:
            return False, "REVIEWED_SOURCE_PARAGRAPH_OTHER_TAXON:"+reviewed_other_taxa[record_no]
    if "OTHER_SPECIES" in scopes or "GIANT_MOTTLED_EEL_ONLY" in scopes:
        return False, "REVIEWED_PARAGRAPH_TAXON_NOT_TARGET_SPECIES"
    if "GENERAL_AQUACULTURE" in scopes:
        return True, "REVIEWED_GENERAL_POND_MECHANISM_NO_SPECIES_NUMERIC_EXTENSION"
    if "GENERAL_DIAGNOSTIC_PROCESS" in scopes:
        if any(s in question for s in ("診斷", "確診", "疾病", "抗生素", "劑量", "健康", "食慾", "攝餌", "游泳", "症狀", "食品安全")):
            return True, "GENERAL_DIAGNOSTIC_REFERRAL_ONLY_NOT_CURRENT_PRESCRIPTION"
        return False, "GENERAL_DIAGNOSTIC_PROCESS_DOES_NOT_ANSWER_OTHER_TOPIC"
    if "GENERAL_FEED_PHYSICAL" in scopes:
        if any(s in question for s in ("浮性", "浮框", "漂散", "細網", "30 cm", "18 cm")):
            return True, "FEED_DEVICE_OR_PHYSICAL_PROPERTY_ONLY_NO_EEL_BIOLOGY_TRANSFER"
        return False, "FEED_PHYSICAL_PROPERTY_NOT_EEL_BIOLOGICAL_RATE"
    if target in scopes:
        pass
    else:
        # Only allow a narrowly named species if the original question itself names it.
        named = [s for s in ("金目鱸", "七星鱸", "日本鰻", "白鰻", "鞍帶石斑", "龍膽石斑", "台灣鯛", "午仔魚") if s in question and s in scopes]
        if not named:
            return False, "SPECIES_SCOPE_NOT_EXACTLY_VERIFIED"
    if source_id == "MOA-ANIMAL-DRUG-OPEN-7274" and any(x.lower() in question.lower() for x in MEDICATION_RISK_TERMS):
        raw = record["original_record_json"]
        if not any(key in raw for key in ("用法用量", "停藥期", "休藥期", "劑量")):
            return False, "DRUG_DATASET_HAS_NO_DOSE_OR_WITHDRAWAL_FIELD"
    return True, "EXACT_RECORD_LEVEL_LITERAL_SPECIES_MATCH"


def collect_retrieval(q: dict[str, Any], profile: dict[str, Any], query_vec: np.ndarray, rows: list[dict[str, Any]], record_map: dict[str, dict[str, Any]], con: sqlite3.Connection, reranker) -> dict[str, Any]:
    question = q["question_text"]
    row_by_id = {r["chunk_id"]: r for r in rows}
    bm25 = fts_bm25(con, question, limit=40)
    dense_scores = [(float(np.dot(query_vec, r["embedding_array"])), r["chunk_id"]) for r in rows]
    dense_scores.sort(key=lambda x: (-x[0], x[1]))
    dense = [{"chunk_id": cid, "dense_score": score} for score, cid in dense_scores[:40]]
    fusion: dict[str, float] = collections.defaultdict(float)
    bm_by = {r["chunk_id"]: r for r in bm25}
    dense_by = {r["chunk_id"]: r for r in dense}
    for rank, row in enumerate(bm25, 1):
        fusion[row["chunk_id"]] += 1.0 / (60 + rank)
    for rank, row in enumerate(dense, 1):
        fusion[row["chunk_id"]] += 1.0 / (60 + rank)
    fused_ids = sorted(fusion, key=lambda cid: (-fusion[cid], cid))
    fused_rows = []
    for rank, cid in enumerate(fused_ids, 1):
        row = row_by_id[cid]
        fused_rows.append({**row, "rrf_score": fusion[cid], "rrf_rank": rank,
                           "bm25_score": bm_by.get(cid, {}).get("bm25_score"), "dense_score": dense_by.get(cid, {}).get("dense_score")})
    # Do not discard supporting sibling spans before the content-aware reranker.
    # Concrete predecessor failure: grouper Q09 retained record 0235 C02 and
    # discarded C03 (virus-free broodstock / seed selection) at RRF deduplication.
    deduped = fused_rows
    scope_pass, scope_excluded = [], []
    for row in deduped:
        record = record_map[row["source_record_id"]]
        ok, reason = source_applicability(row, profile, record)
        if ok:
            row["scope_gate"] = {"eligible": True, "reason": reason, "species_scope": row["species_scope_list"]}
            scope_pass.append(row)
        else:
            scope_excluded.append({"chunk_id": row["chunk_id"], "source_id": row["source_id"], "source_record_id": row["source_record_id"], "reason": reason, "species_scope": row["species_scope_list"]})
    rank_inputs = [{"chunk_id": r["chunk_id"], "text": r["text"], "rank": r["rrf_rank"], "rrf_rank": r["rrf_rank"]} for r in scope_pass]
    reranked = reranker.rerank(question, rank_inputs) if rank_inputs else []
    rerank_map = {r["chunk_id"]: r for r in reranked}
    scope_by_id = {r["chunk_id"]: r for r in scope_pass}
    final = []
    seen_records = set()
    for rr in reranked:
        # Keep the pre-rerank provenance and stable ranks from the exact candidate row.
        source = scope_by_id[rr["chunk_id"]]
        record = record_map[source["source_record_id"]]
        key = record.get("duplicate_group_id") or source["source_record_id"]
        if key in seen_records:
            continue
        seen_records.add(key)
        rank = len(final)+1
        final.append({
            "question_id": q["question_id"], "chunk_id": source["chunk_id"], "rank": rank, "source_id": source["source_id"],
            "source_record_id": source["source_record_id"], "source_record_locator": record["source_record_locator"],
            "document_id": source["source_id"], "source_sha256": source["source_sha256"], "source_version": source["source_version"],
            "exact_locator": source["locator"], "raw_field_pointer": source["raw_field_pointer"], "source_quote": source["source_quote"],
            "text": source["text"], "content_sha256": source["content_sha256"], "context_sha256": sha256_text(source["text"]),
            "species_scope": source["species_scope_list"], "category_scope": source["category_scope_list"], "retrieval_eligible": True,
            "source_cluster_id": source["source_cluster_id"], "processing_scope": source["processing_scope"],
            "bm25_score": bm_by.get(source["chunk_id"], {}).get("bm25_score"), "dense_score": dense_by.get(source["chunk_id"], {}).get("dense_score"),
            "rrf_score": fusion[source["chunk_id"]], "rrf_rank": source["rrf_rank"], "reranker_score": rr.get("reranker_score"),
            "reranker_rank": rr.get("reranker_rank"), "source_applicability_reason": source["scope_gate"]["reason"],
        })
        if len(final)==5:
            break
    return {
        "question_id": q["question_id"], "question": question, "species": q["species_chinese"], "category": q.get("inferred_category"),
        "corpus_id": "marine_hybrid_rag_corpus_v3_research_isolated", "corpus_sha256": None,
        "retrieval_config": {"bm25": "SQLite FTS5 BM25 on CJK bigram tokens", "bm25_candidate_limit": 40, "dense_model": EMBED_MODEL, "dense_digest": EMBED_DIGEST, "dense_normalized_l2": True, "dense_candidate_limit": 40, "rrf_k": 60, "reranker": "BAAI/bge-reranker-v2-m3", "reranker_snapshot": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "rerank_candidates": len(scope_pass), "top_k_requested": 5},
        "candidate_counts": {"corpus_retrieval_eligible_chunks": len(rows), "bm25_raw_matching": len(bm25), "bm25_returned": len(bm25), "dense_raw": len(rows), "dense_returned": len(dense), "rrf_fused_unique_chunks": len(fused_rows),
                             "rrf_after_record_dedupe": len(deduped), "source_scope_pass": len(scope_pass), "source_scope_excluded": len(scope_excluded), "reranker_candidates": len(reranked), "final_top_k": len(final)},
        "bm25_candidates": [{"chunk_id": r["chunk_id"], "score": r["bm25_score"]} for r in bm25],
        "dense_candidates": [{"chunk_id": r["chunk_id"], "score": r["dense_score"]} for r in dense],
        "rrf_candidates": [{"chunk_id": cid, "source_record_id": row_by_id[cid]["source_record_id"], "score": fusion[cid], "rrf_rank": i+1} for i,cid in enumerate(fused_ids)],
        "scope_excluded": scope_excluded, "reranker_order": [{"chunk_id": r["chunk_id"], "reranker_score": r.get("reranker_score"), "reranker_rank": r.get("reranker_rank")} for r in reranked],
        "top5": final, "empty_result_reason": None if final else ("NO_BM25_OR_DENSE_CANDIDATES" if not fused_rows else "NO_SOURCE_OR_SPECIES_APPLICABILITY_CANDIDATE"),
    }


def requirement_assessment(q: dict[str, Any], profile: dict[str, Any], hit: dict[str, Any], record_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = record_map[hit["source_record_id"]]
    payload = row["original_record_json"]
    question = q["question_text"]
    source_id = hit["source_id"]
    full_text = hit["text"]
    numeric_tokens = re.findall(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?", full_text)
    wants_value = profile["required_values_or_ranges"] == "required"
    units_in_question = profile["required_units"]
    units_missing = [u for u in units_in_question if u not in full_text]
    condition_missing = [c for c in profile["required_conditions"] if c not in full_text]
    overlap_title = 0.0
    if source_id == "MOA-TFRI-OPEN-114846":
        title = str(payload.get("title", ""))
        answer = str(payload.get("description", ""))
        overlap_title = jaccard(question, title)
        overlap_answer = jaccard(question, answer)
        overlap = max(overlap_title, overlap_answer)
        if overlap < 0.06:
            status, reason = "IRRELEVANT", "Deterministic CJK-term screen found little non-species query/evidence overlap; diagnostic only."
        elif wants_value and not numeric_tokens:
            status, reason = "TOPICAL_ONLY", "Question requires a value/range but this chunk contains no numeric token."
        elif profile["required_conditions"] and condition_missing:
            status, reason = "PARTIAL_SUPPORT", "Potential topic/answer overlap, but at least one explicit question condition is absent from this span."
        elif overlap_title >= 0.32 and overlap_answer >= 0.12 and (not wants_value or bool(numeric_tokens)) and not units_missing:
            status, reason = "FULL_SUPPORT", "Same-source Q&A title and answer contain measurable overlap and satisfy the parsed value/unit/condition checks; automated candidate, not Human Gold."
        elif overlap >= 0.13:
            status, reason = "PARTIAL_SUPPORT", "Source Q&A overlaps with some requested content but the conservative full-support checks are not met."
        else:
            status, reason = "TOPICAL_ONLY", "Species/topic overlap without a sufficiently direct answer match."
        matched = sorted(meaningful_tokens(question) & meaningful_tokens(answer))
    elif source_id == "MOA-ANIMAL-DRUG-OPEN-7274":
        product = str(payload.get("動物用藥品中文名稱", ""))
        permit = str(payload.get("許可證字號", ""))
        indication = str(payload.get("效能(適應症)", ""))
        named_product = bool(product and product in question) or bool(permit and permit in question)
        asks_supported_field = any(t in question for t in ["名稱", "成分", "適應症", "許可證", "有效期間", "有效期限"])
        if any(x.lower() in question.lower() for x in MEDICATION_RISK_TERMS):
            status, reason = "TOPICAL_ONLY", "Dataset has no dose/withdrawal field; drug name or indication cannot support requested clinical instructions."
        elif named_product and asks_supported_field:
            status, reason = "PARTIAL_SUPPORT", "Named product/permit record can support only the fields explicitly present; not current use advice."
        else:
            status, reason = "TOPICAL_ONLY", "Exact species appears in source indication but question is not directly mapped to a named permit field."
        matched = [x for x in [product, permit] if x and x in question] + (["indication_field"] if indication and any(t in indication for t in question.split()) else [])
        overlap = jaccard(question, " ".join([product, permit, indication]))
        overlap_title = 0.0
    else:
        native_category = str(payload.get("original_category_label", ""))
        stats_question = any(t in question for t in STAT_TERMS) and ("2020" in question or "109" in question)
        category_match = native_category.rstrip("類") in question if native_category else False
        if stats_question and category_match and numeric_tokens:
            status, reason = "PARTIAL_SUPPORT", "Exact DGBAS value is available for a native statistical category; cannot imply exact biological species or husbandry."
        else:
            status, reason = "TOPICAL_ONLY", "DGBAS native statistic does not answer non-statistical aquaculture questions."
        matched = [native_category] if native_category and category_match else []
        overlap = jaccard(question, full_text)
        overlap_title = 0.0
    return {
        "question_id": q["question_id"], "chunk_id": hit["chunk_id"], "rank": hit["rank"], "source_id": source_id,
        "source_record_id": hit["source_record_id"], "source_version": hit["source_version"], "source_sha256": hit["source_sha256"],
        "exact_locator": hit["exact_locator"], "exact_evidence_span": hit["source_quote"], "evidence_status": status,
        "matched_answer_elements": matched, "missing_answer_elements": profile["required_answer_elements"] if status not in {"FULL_SUPPORT"} else [],
        "required_values_or_ranges": profile["required_values_or_ranges"], "numeric_tokens_in_context": numeric_tokens,
        "required_units": units_in_question, "missing_units": units_missing, "required_conditions": profile["required_conditions"],
        "missing_conditions": condition_missing, "species_applicability": "EXACT_LITERAL_MATCH_AFTER_GATE",
        "source_identity_status": "VERIFIED_SOURCE_REGISTRY_AND_CHECKSUM", "support_method": "conservative deterministic checks against raw source record and exact locator; not human relevance gold",
        "title_overlap_jaccard": overlap_title, "content_overlap_jaccard": overlap if "overlap" in locals() else 0.0,
        "reason": reason, "human_gold_status": "NOT_HUMAN_GOLD", "needs_human_review": status in {"FULL_SUPPORT", "PARTIAL_SUPPORT", "CONDITION_MISMATCH"},
    }


def all_corpus_direct_match(q: dict[str, Any], profile: dict[str, Any], records: list[dict[str, Any]], chunk_meta: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for r in records:
        if r["source_id"] != "MOA-TFRI-OPEN-114846":
            continue
        payload = r["original_record_json"]
        title = str(payload.get("title", ""))
        answer = str(payload.get("description", ""))
        scopes = [t for t in SPECIES if t in title + answer]
        if q["species_chinese"] not in scopes:
            continue
        title_score = jaccard(q["question_text"], title)
        answer_score = jaccard(q["question_text"], answer)
        numbers = re.findall(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?", clean_text(answer))
        required_value = profile["required_values_or_ranges"] == "required"
        value_ready = not required_value or bool(numbers)
        direct = title_score >= 0.50 and answer_score >= 0.12 and value_ready
        candidates.append((direct, max(title_score, answer_score), title_score, answer_score, r, payload, numbers))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (not x[0], -x[1], x[4]["source_record_id"]))
    direct, score, title_score, answer_score, r, payload, numbers = candidates[0]
    if not direct:
        return {"status": "PARTIALLY_SUPPORTED", "candidate_source_record_id": r["source_record_id"], "title": payload.get("title"), "title_similarity": title_score, "answer_similarity": answer_score, "reason": "An exact-species source Q&A is topically similar but does not meet the direct-answer threshold."}
    text = clean_text(str(payload.get("description", "")))
    return {"status": "ANSWERABLE_AUTO_SOURCE_CHECKED", "candidate_source_record_id": r["source_record_id"], "source_id": r["source_id"],
            "source_sha256": "66e1803c1bac11aef1dd887c798767773603e1c1274d274cafa153c36a318446", "source_version": "official JSON snapshot 2026-10-20; record pubdate=" + str(payload.get("pubdate", "")),
            "locator": r["source_record_locator"] + "; fields /title and /description", "source_question": payload.get("title"), "source_answer": text,
            "title_similarity": title_score, "answer_similarity": answer_score, "numeric_values_present": numbers,
            "verification_method": "record-level deterministic title/answer similarity + exact target species + required-value presence; automated candidate, not expert validation",
            "human_gold_status": "NOT_HUMAN_GOLD", "limitations": "Potential direct answer mapping requires researcher review; score is not a formal gold label."}


def clean_text(text: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    import html
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def run() -> None:
    questions = read_jsonl(QUESTION_FILE)
    if len(questions) != 180 or len({q["question_id"] for q in questions}) != 180:
        raise RuntimeError(f"Question source mismatch: rows={len(questions)}, unique={len({q['question_id'] for q in questions})}")
    rows, record_map, sources = load_chunks()
    if len(rows) != 2354:
        raise RuntimeError(f"Unexpected retrieval-eligible chunk count {len(rows)}")
    profiles = [make_requirement_profile(q) for q in questions]
    write_jsonl(WORK / "question_requirement_profiles_180.jsonl", profiles)
    query_vectors = {}
    cache = WORK / "query_embedding_checkpoint.jsonl"
    if cache.exists():
        for r in read_jsonl(cache):
            arr = np.asarray(r.get("embedding", []), dtype=np.float32)
            if arr.shape == (1024,):
                query_vectors[r["question_id"]] = arr
    missing = [q for q in questions if q["question_id"] not in query_vectors]
    with cache.open("a", encoding="utf-8", newline="\n") as f:
        for start in range(0, len(missing), 16):
            batch = missing[start:start+16]
            vectors = _embed([q["question_text"] for q in batch])
            for q, vec in zip(batch, vectors, strict=True):
                query_vectors[q["question_id"]] = vec
                f.write(json.dumps({"question_id":q["question_id"],"embedding":vec.tolist()},separators=(",",":"))+"\n")
            f.flush()
    reranker = load_reranker()
    reranker_metadata = {"model_id":"BAAI/bge-reranker-v2-m3","snapshot":"953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e","device":reranker.load_info.device,"dtype":"float32","max_sequence_length":512,"batch_size":8,"tokenizer_class":reranker.load_info.tokenizer_class,"tokenizer_is_fast":reranker.load_info.tokenizer_is_fast,"model_class":reranker.load_info.model_class,"parameter_count":reranker.load_info.parameter_count,"load_seconds":reranker.load_info.model_load_seconds}
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    retrievals, label_rows, support_rows, eligibility_rows = [], [], [], []
    profile_map = {p["question_id"]:p for p in profiles}
    old_refs = {r["question_id"]:r for r in read_jsonl(AA_REFS)}
    all_records = list(record_map.values())
    # New checkpoint namespace after duplicate-group registration. The previous
    # checkpoint and result are retained as provenance and are not reused.
    checkpoint = WORK / "retrieval_verification_checkpoint_v2.jsonl"
    checkpoint_rows = {r["question_id"]: r for r in read_jsonl(checkpoint)} if checkpoint.exists() else {}
    checkpoint_qids = set(checkpoint_rows)
    start_all = time.perf_counter()
    with checkpoint.open("a", encoding="utf-8", newline="\n") as checkpoint_file:
      for idx, q in enumerate(questions, 1):
        if q["question_id"] in checkpoint_rows:
            saved = checkpoint_rows[q["question_id"]]
            retrievals.append(saved["retrieval"])
            label_rows.extend(saved["labels"])
            support_rows.extend(saved["support"])
            eligibility_rows.append(saved["eligibility"])
            continue
        profile = profile_map[q["question_id"]]
        result = collect_retrieval(q, profile, query_vectors[q["question_id"]], rows, record_map, con, reranker)
        result["corpus_sha256"] = hashlib.sha256(DB.read_bytes()).hexdigest()
        retrievals.append(result)
        question_labels, question_support = [], []
        for hit in result["top5"]:
            label = requirement_assessment(q, profile, hit, record_map)
            question_labels.append(label)
            question_support.append({"question_id":q["question_id"],"species":q["species_chinese"],"category":q.get("inferred_category"), **label})
        label_rows.extend(question_labels)
        support_rows.extend(question_support)
        direct_match = all_corpus_direct_match(q, profile, all_records, {})
        top_status = [x["evidence_status"] for x in [requirement_assessment(q, profile, h, record_map) for h in result["top5"]]]
        if direct_match and direct_match.get("status") == "ANSWERABLE_AUTO_SOURCE_CHECKED":
            eligibility_status = "ANSWERABLE_AUTO_SOURCE_CHECKED"
            reason = "A direct exact-species Q&A answer candidate exists in the admitted corpus outside any top-5 requirement; deterministic mapping is not Human Gold."
        elif any(s in {"FULL_SUPPORT", "PARTIAL_SUPPORT"} for s in top_status):
            eligibility_status = "PARTIALLY_SUPPORTED"
            reason = "At least one retrieved span has a deterministic partial/direct-content candidate, but no frozen human-verified answer rubric."
        else:
            eligibility_status = "NOT_EVALUABLE"
            reason = "No direct source-verified answer mapping was established. Empty Top-5 or failed retrieval is not proof that the question is unanswerable globally."
        if any(x in q["question_text"] for x in ["停藥", "休藥", "劑量", "用量"]) and eligibility_status == "NOT_EVALUABLE":
            reason += " Drug source has no verified dose/withdrawal field; no dose or withdrawal truth inferred."
        old = old_refs.get(q["question_id"])
        eligibility = {
            "question_id":q["question_id"],"species":q["species_chinese"],"category":q.get("inferred_category"),"original_question":q["question_text"],
            "candidate_answer_preserved_for_audit":q.get("candidate_reference_answer"),"candidate_answer_used_for_source_matching":False,
            "eligibility_status":eligibility_status,"eligibility_reason":reason,"corpus_contains_direct_answer_candidate":bool(direct_match and direct_match.get("status")=="ANSWERABLE_AUTO_SOURCE_CHECKED"),
            "direct_match":direct_match,"retrieval_top5_count":len(result["top5"]),"retrieval_is_eligibility_precondition":False,
            "historical_phase_aa_reference": {"verification_status":old.get("verification_status"),"old_source_id":old.get("source_id"),"revalidated_in_corpus_v3":False if not direct_match else True} if old else None,
            "human_gold_status":"NOT_HUMAN_GOLD","verification_level":"AUTO_SOURCE_CHECKED_CANDIDATE" if eligibility_status=="ANSWERABLE_AUTO_SOURCE_CHECKED" else "NOT_EVALUABLE_AUTOMATED_SCREEN",
        }
        eligibility_rows.append(eligibility)
        saved = {"question_id": q["question_id"], "retrieval": result, "labels": question_labels, "support": question_support, "eligibility": eligibility}
        checkpoint_file.write(json.dumps(saved, ensure_ascii=False, sort_keys=True) + "\n")
        checkpoint_file.flush()
        if idx%30==0:
            print(f"retrieved {idx}/180",flush=True)
    con.close()
    write_jsonl(WORK / "retrieval_results_v3_180.jsonl", retrievals)
    write_jsonl(WORK / "retrieved_context_relevance_labels.jsonl", label_rows)
    write_jsonl(WORK / "evidence_support_verification_180.jsonl", support_rows)
    write_jsonl(WORK / "question_eligibility_180.jsonl", eligibility_rows)
    refs = []
    for row in eligibility_rows:
        direct = row.get("direct_match") or {}
        refs.append({"question_id":row["question_id"],"species":row["species"],"category":row["category"],"original_question":row["original_question"],
                     "reference_answer":direct.get("source_answer"),"required_answer_elements":profile_map[row["question_id"]]["required_answer_elements"],
                     "source_ids":[direct.get("source_id")] if direct.get("source_id") else [],"exact_evidence_spans":[direct.get("source_answer")] if direct.get("source_answer") else [],
                     "source_version":direct.get("source_version"),"exact_locator":direct.get("locator"),"required_conditions":profile_map[row["question_id"]]["required_conditions"],
                     "numeric_values":direct.get("numeric_values_present",[]),"units":profile_map[row["question_id"]]["required_units"],"logical_rubric":None,"arithmetic_formula":None,"arithmetic_tolerance":None,
                     "evidence_verification_status":direct.get("status","NOT_EVALUABLE"),"verification_method":direct.get("verification_method"),
                     "human_review_status":"PENDING","human_gold_status":"NOT_HUMAN_GOLD","limitations":direct.get("limitations",row["eligibility_reason"])})
    write_jsonl(WORK / "verified_reference_answers_180.jsonl", refs)
    rubrics = {"rubric_version":"evaluation_rubrics_v3_draft_1.0.0","frozen_before_new_generator_answers":True,"human_gold_count":0,
               "general_accuracy_rule":"Accuracy=N_correct/N_evaluable; only source-verified answers and pre-frozen observable rubric can be evaluated.",
               "context_precision_at_5":{"definition":"Relevant Top-5 count / 5","evaluable_question_count":0,"reason":"No human-confirmed binary chunk relevance labels were produced in this phase; the deterministic labels are diagnostic candidates, not P@5 gold."},
               "logical_accuracy":{"evaluable_question_count":0,"reason":"No independent human-reviewed answer rubric. Reference candidates are automated source matches only."},
               "arithmetic_accuracy":{"evaluable_question_count":0,"reason":"No source-verified formula protocol, conditions, units and tolerance subset was frozen from this integrated corpus."},
               "eligible_answer_rubric_candidates":sum(1 for r in refs if r["evidence_verification_status"]=="ANSWERABLE_AUTO_SOURCE_CHECKED"),
               "rubric_policy":"No generator outputs were consulted; no missing values imputed; AI source checks remain NOT_HUMAN_GOLD."}
    write_json(WORK / "evaluation_rubrics_v3.json", rubrics)
    species_summary={}
    for fish in SPECIES:
        qs=[r for r in eligibility_rows if r["species"]==fish]
        contexts=[l for l in label_rows if any(r["question_id"]==l["question_id"] and r["species"]==fish for r in qs)]
        species_summary[fish]={"question_count":len(qs),"with_any_context":sum(1 for r in retrievals if r["species"]==fish and r["top5"]),"full_top5":sum(1 for r in retrievals if r["species"]==fish and len(r["top5"])==5),
                              "eligibility_counts":dict(collections.Counter(r["eligibility_status"] for r in qs)),"diagnostic_evidence_status_counts":dict(collections.Counter(c["evidence_status"] for c in contexts)),
                              "literal_source_chunk_count":sum(1 for r in rows if fish in r["species_scope_list"])}
    write_json(WORK / "six_species_evidence_coverage.json", {"method":"exact literal species scope; question counts from Phase A normalization; top5 diagnostics not ground truth", "species":species_summary,"total_questions":180,"human_gold":0})
    label_counts=collections.Counter(x["evidence_status"] for x in label_rows)
    ret_counts=collections.Counter(len(r["top5"]) for r in retrievals)
    elig_counts=collections.Counter(r["eligibility_status"] for r in eligibility_rows)
    p5={"metric":"Context Precision@5","formula":"Relevant chunks in Top-5 / 5","human_or_independent_binary_labels":0,"questions_with_reliable_binary_relevance_labels":0,"evaluable_exact_p5_questions":0,"mean":None,"status":"NOT_EVALUABLE","reason":"The chunk support classifications are deterministic source/requirement diagnostics; no human relevance labels. Reranker scores are not relevance labels."}
    write_json(WORK / "context_precision_readiness.json", p5)
    write_json(WORK / "retrieval_and_evidence_summary.json", {"questions":180,"questions_with_any_context":sum(1 for r in retrievals if r["top5"]),"questions_full_top5":sum(1 for r in retrievals if len(r["top5"])==5),
                "context_count_distribution":dict(ret_counts),"candidate_evidence_diagnostic_counts":dict(label_counts),"eligibility_counts":dict(elig_counts),
                "reranker":reranker_metadata,"elapsed_seconds":time.perf_counter()-start_all,"retrieval_is_research_candidate_not_gold":True,
                "p_at_5":p5,"logical_accuracy":{"N":0,"status":"NOT_EVALUABLE"},"arithmetic_accuracy":{"N":0,"status":"NOT_EVALUABLE"}})
    print(json.dumps({"retrieval_questions":len(retrievals),"with_context":sum(bool(r["top5"]) for r in retrievals),"full_top5":sum(len(r["top5"])==5 for r in retrievals),
                      "eligibility":dict(elig_counts),"diagnostic_labels":dict(label_counts),"elapsed_seconds":round(time.perf_counter()-start_all,2)},ensure_ascii=False))


if __name__ == "__main__":
    run()
