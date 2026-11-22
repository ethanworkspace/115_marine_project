from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
Z = ROOT / "reports/evaluation/fish_test_phase_z_20261019_173013"
V = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918"
MODEL = "bge-m3:latest"
EXPECTED_EMBED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
RERANKER_ID = "BAAI/bge-reranker-v2-m3"
RERANKER_SNAPSHOT = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
NOW = datetime.now(timezone.utc).isoformat()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def norm_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def exact_quote(page_text: str, quote: str) -> tuple[int | None, int | None, str | None]:
    if not quote:
        return None, None, None
    at = page_text.find(quote)
    if at >= 0:
        return at, at + len(quote), page_text[at:at + len(quote)]
    pattern = re.sub(r"\\\s+", r"\\s+", re.escape(quote.strip()))
    match = re.search(pattern, page_text, flags=re.S)
    if match:
        return match.start(), match.end(), page_text[match.start():match.end()]
    # The old card format may have collapsed line breaks. Compare the collapsed
    # strings, then retain a verifiable actual source substring where possible.
    collapsed_page = norm_ws(page_text)
    collapsed_quote = norm_ws(quote)
    at = collapsed_page.find(collapsed_quote)
    if at >= 0:
        # Offset mapping is not stable after whitespace collapse. Do not invent
        # offsets: mark quote as normalized-match-only for manual review.
        return None, None, "NORMALIZED_MATCH_ONLY"
    return None, None, None


def import_pymupdf():
    for item in (ROOT / ".venv-reranker/Lib/site-packages", ROOT / ".venv/Lib/site-packages"):
        if item.exists():
            sys.path.insert(0, str(item.resolve()))
    try:
        import pymupdf  # type: ignore
    except ImportError:
        import fitz as pymupdf  # type: ignore
    return pymupdf


def local_path(record: dict[str, Any]) -> Path | None:
    value = record.get("local_file") or record.get("source_file")
    if not value:
        return None
    p = Path(str(value))
    if not p.is_absolute():
        p = ROOT / p
    return p


def load_inputs():
    blockers = read_jsonl(Z / "source_blocker_review_50.jsonl")
    cards = read_jsonl(V / "evidence_cards_v3.jsonl")
    refs = read_jsonl(Z / "reference_answers_frozen.jsonl")
    independent = read_jsonl(Z / "independent_test_set.jsonl")
    assert len(blockers) == 50, f"expected 50 source blockers, got {len(blockers)}"
    assert len(cards) == 25, f"expected 25 existing cards, got {len(cards)}"
    assert len(refs) == 15, f"expected 15 source answer records, got {len(refs)}"
    return blockers, cards, refs, independent


def source_use_review(blockers: list[dict[str, Any]], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_hashes = {str(c.get("source_sha256", "")).lower() for c in cards}
    card_sources = sorted({str(c.get("source_id")) for c in cards})
    rows: list[dict[str, Any]] = []
    pymupdf = import_pymupdf()
    for record in blockers:
        path = local_path(record)
        exists = bool(path and path.is_file())
        actual = sha_file(path) if exists and path else None
        sha_match = bool(actual and actual.lower() == str(record.get("sha256_expected", "")).lower())
        publisher = record.get("publisher_recorded")
        if publisher in (None, "UNVERIFIED"):
            publisher = None
        doc_meta: dict[str, Any] = {}
        page_count = None
        rights_hits: list[str] = []
        extracted_text_chars = 0
        if exists and path and path.suffix.lower() == ".pdf":
            try:
                with pymupdf.open(path) as doc:
                    doc_meta = {k: v for k, v in (doc.metadata or {}).items() if v not in (None, "")}
                    page_count = len(doc)
                    texts = [p.get_text() for p in doc]
                    extracted_text_chars = sum(map(len, texts))
                    whole = "\n".join(texts)
                    for pattern in [r"©[^\n]{0,120}", r"copyright[^\n]{0,120}", r"著作權[^\n]{0,120}", r"版權所有[^\n]{0,120}", r"政府資料開放授權[^\n]{0,120}", r"Creative Commons[^\n]{0,120}"]:
                        rights_hits.extend(re.findall(pattern, whole, flags=re.I))
            except Exception as exc:
                doc_meta = {"inspection_error": f"{type(exc).__name__}: {exc}"}
        elif exists and path and path.suffix.lower() in {".html", ".htm"}:
            raw = path.read_text(encoding="utf-8", errors="replace")
            extracted_text_chars = len(raw)
            for pattern in [r"©[^<\n]{0,120}", r"copyright[^<\n]{0,120}", r"著作權[^<\n]{0,120}", r"政府資料開放授權[^<\n]{0,120}"]:
                rights_hits.extend(re.findall(pattern, raw, flags=re.I))
        in_card_scope = bool(actual and actual.lower() in card_hashes)
        if in_card_scope and sha_match:
            usage_class = "LIMITED_RESEARCH_FACT_CARD_ONLY"
            processing_status = "ELIGIBLE_FOR_REVALIDATED_SHORT_FACT_CARDS_ONLY"
            allowed_scope = "Concise researcher-authored factual/method statement for local non-public research; exact short source locator quote held as provenance, not indexed; no source PDF/HTML full-text index or redistribution. Not formal Corpus admission."
        else:
            usage_class = "FULLTEXT_RIGHTS_UNVERIFIED; FACT_CARD_SCOPE_NOT_ESTABLISHED"
            processing_status = "RESTRICTED_PENDING_BASIS_OR_REPLACEMENT"
            allowed_scope = "Local integrity/content review only; do not include source text in retrieval index. Revisit only with exact official/open license, applicable statutory basis, or narrowly supported fact-card scope."
        if not sha_match:
            processing_status = "BLOCKED_SOURCE_FILE_MISSING_OR_HASH_MISMATCH"
            usage_class = "SOURCE_IDENTITY_NOT_VERIFIED"
        rec = {
            "source_record_id": record.get("source_record_id"),
            "source_id": record.get("source_id"),
            "title_recorded": record.get("title_recorded"),
            "local_file": str(path) if path else record.get("local_file"),
            "file_exists": exists,
            "expected_sha256": record.get("sha256_expected"),
            "actual_sha256": actual,
            "sha256_match": sha_match,
            "duplicate_sha256_group": None,
            "format": record.get("format"),
            "pdf_metadata": doc_meta,
            "page_count": page_count,
            "extractable_characters": extracted_text_chars,
            "publisher_evidence_in_original": publisher or doc_meta.get("author") or doc_meta.get("creator") or None,
            "recorded_official_url": record.get("official_url_recorded"),
            "recorded_version": record.get("document_version_recorded"),
            "license_or_rights_text_hits": list(dict.fromkeys(rights_hits)),
            "owner_decision": "APPROVED_FOR_RESEARCH_PROCESSING_DECISION; NOT_THIRD_PARTY_LICENSE",
            "use_classification": usage_class,
            "processing_status": processing_status,
            "permitted_processing_scope": allowed_scope,
            "fulltext_index_permission_verified": False,
            "third_party_express_license_claimed": False,
            "formal_source_admission": False,
            "card_source_ids_in_revalidated_scope": card_sources if in_card_scope else [],
            "publisher_version_species_followup": "Observed from local original metadata/content and linked Phase V card record; external source publication/rights not uniformly proven for this file.",
            "evidence_references": [
                "Taiwan Copyright Act Arts. 9 and 10-1; application depends on exact material and use, not owner decision.",
                "Official publisher terms must be matched to this exact resource before full-text indexing.",
            ],
            "reviewed_at_utc": NOW,
        }
        rows.append(rec)
    # Mark duplicate file records without deleting either trace.
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if row.get("actual_sha256"):
            groups[row["actual_sha256"]].append(idx)
    for digest, indices in groups.items():
        if len(indices) > 1:
            gid = "sha256:" + digest
            for idx in indices:
                rows[idx]["duplicate_sha256_group"] = gid
    return rows


SPECIES_OVERRIDE = {
    "TFRI-M17-GOLD-SEABASS": ("金目鱸", "Lates calcarifer", "SPECIES_SPECIFIC"),
    "TFRI-M17-SEVENSTAR": ("七星鱸", "Lateolabrax japonicus", "SPECIES_SPECIFIC"),
    "TFRI-M17-MULLET": ("烏魚", "Mugil cephalus", "SPECIES_SPECIFIC"),
    "TFRI-M17-GROUPER": ("石斑魚（手冊界定群組）", "Epinephelinae / source-defined grouper group", "SOURCE_DEFINED_GROUP"),
    "TFRI-EEL-MOLD-2006": ("鰻魚（台灣養殖脈絡；章節需個別核對白鰻物種）", "Anguilla spp. as described in source; not current advice", "SOURCE_DEFINED_EEL_SCOPE"),
    "FA-385-COLD": ("虱目魚、吳郭魚；部分卡另含一般養殖事項", "Chanos chanos; Oreochromis spp. as stated in source", "MULTI_SPECIES_WITH_SOURCE_LABELS"),
}


def locate_card_source(card: dict[str, Any], blocker_by_sha: dict[str, dict[str, Any]], refs: list[dict[str, Any]]) -> Path | None:
    digest = str(card.get("source_sha256", "")).lower()
    rec = blocker_by_sha.get(digest)
    if rec:
        p = local_path(rec)
        if p and p.is_file() and sha_file(p).lower() == digest:
            return p
    for ref in refs:
        if str(ref.get("source_sha256_actual", "")).lower() == digest:
            p = Path(ref.get("source_file", ""))
            if not p.is_absolute():
                p = ROOT / p
            if p.is_file() and sha_file(p).lower() == digest:
                return p
    return None


def revalidate_existing_cards(cards: list[dict[str, Any]], blockers: list[dict[str, Any]], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pymupdf = import_pymupdf()
    by_sha = {str(r.get("sha256_actual") or r.get("sha256_expected") or "").lower(): r for r in blockers}
    checked: list[dict[str, Any]] = []
    for card in cards:
        path = locate_card_source(card, by_sha, refs)
        digest = str(card.get("source_sha256", "")).lower()
        metadata = card.get("metadata") or {}
        locator = str(card.get("record_locator", ""))
        match = re.search(r"physical page\s+(\d+)", locator, flags=re.I)
        page_no = int(match.group(1)) if match else None
        quote = str(metadata.get("evidence_span") or "")
        result = {
            **card,
            "qa_validation": {
                "local_source_found": bool(path),
                "source_path": str(path) if path else None,
                "source_sha256_rechecked": sha_file(path) if path else None,
                "source_sha256_match": bool(path and sha_file(path).lower() == digest),
                "page_number": page_no,
                "exact_source_quote": None,
                "quote_start_char": None,
                "quote_end_char": None,
                "quote_location_status": "NOT_CHECKED",
                "version_present": bool(card.get("source_version")),
                "scope_status": "SOURCE_SPECIFIC_METADATA_RETAINED",
                "human_gold": False,
                "formal_admission": False,
            },
        }
        if path and page_no and sha_file(path).lower() == digest:
            try:
                with pymupdf.open(path) as doc:
                    if page_no <= len(doc):
                        page_text = doc[page_no - 1].get_text()
                        start, end, actual_quote = exact_quote(page_text, quote)
                        result["qa_validation"].update({
                            "source_page_sha256": sha_bytes(page_text.encode("utf-8")),
                            "exact_source_quote": actual_quote,
                            "quote_start_char": start,
                            "quote_end_char": end,
                            "quote_location_status": "EXACT_SOURCE_SPAN_VERIFIED" if actual_quote and start is not None else "NORMALIZED_ONLY_REVIEW_REQUIRED" if actual_quote else "QUOTE_NOT_FOUND",
                        })
            except Exception as exc:
                result["qa_validation"]["quote_location_status"] = f"PDF_READ_ERROR:{type(exc).__name__}"
        result["qa_validation"]["research_card_retrieval_eligible"] = bool(
            result["qa_validation"]["source_sha256_match"]
            and result["qa_validation"]["quote_location_status"] == "EXACT_SOURCE_SPAN_VERIFIED"
            and card.get("retrieval_eligible")
            and metadata.get("evidence_quote_verified") is True
        )
        source_species, scientific_name, scope_type = SPECIES_OVERRIDE.get(str(card.get("source_id")), (str(metadata.get("species_scope", "UNKNOWN")), None, "SOURCE_METADATA"))
        result["verified_scope"] = {"source_species_label": source_species, "scientific_name_or_scope": scientific_name, "taxonomy_level": scope_type}
        result["qa_validation"]["processing_scope"] = "RESEARCH_FACT_CARD_NONPUBLIC; NO_FULLTEXT_INDEX; NOT_FORMAL_CORPUS_ADMISSION"
        checked.append(result)
    return checked


def add_new_eel_cards(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pymupdf = import_pymupdf()
    wanted = ["07鰻魚養殖要點及池塘清理消毒.pdf", "02鰻魚寄生蟲病.pdf"]
    by_title = {str(r.get("title_recorded")): r for r in blockers}
    rows = []
    specs = [
        (wanted[0], 1, "最適合生長的水溫為20－30℃", "白鰻（Anguilla japonica）歷史養殖章節記載最適生長水溫為20–30°C；該文為2006年傳統池塘管理脈絡，僅作歷史來源事實，不代表現行建議。", "eel-2006-temp", "Water Quality", ["20", "30"], [["°C", "℃"]]),
        (wanted[1], 1, "寄生蟲疾病的病例數最高（46 件，佔總量22%）", "水試所特刊整理的台灣鰻魚養殖1988年病例中，寄生蟲疾病46件、占當年所列總量22%；這是1988年歷史病例統計，不得推論當前盛行率。", "eel-1988-parasite-cases", "Disease", ["1988", "46", "22%"], []),
    ]
    for filename, page_no, quote, text, fact_id, category, numbers, unit_groups in specs:
        rec = by_title.get(filename)
        path = local_path(rec) if rec else None
        if not path or not path.is_file():
            rows.append({"fact_id": fact_id, "validation_status": "SOURCE_FILE_MISSING", "filename": filename})
            continue
        digest = sha_file(path)
        if digest.lower() != str((rec or {}).get("sha256_expected", "")).lower():
            rows.append({"fact_id": fact_id, "validation_status": "SOURCE_SHA_MISMATCH", "source_sha256": digest})
            continue
        with pymupdf.open(path) as doc:
            page_text = doc[page_no - 1].get_text()
            start, end, actual = exact_quote(page_text, quote)
            if not actual or start is None:
                rows.append({"fact_id": fact_id, "validation_status": "QUOTE_NOT_EXACTLY_LOCATABLE", "source_sha256": digest, "quote": quote})
                continue
        source_id = "TFRI-EEL-HEALTH-SPECIAL-8-2006" if filename.startswith("07") else "TFRI-EEL-PARASITE-SPECIAL-8-2006"
        rows.append({
            "chunk_id": "aa-eel-" + fact_id,
            "source_id": source_id,
            "source_sha256": digest,
            "source_version": "水產試驗所特刊第8號，2006；" + ("pp.113–128" if filename.startswith("07") else "pp.13–50"),
            "record_locator": f"PDF physical page {page_no}; printed page " + ("113" if filename.startswith("07") else "13"),
            "content_sha256": sha_bytes(text.encode("utf-8")),
            "text": text,
            "retrieval_eligible": True,
            "chunk_role": "researcher_authored_historical_fact_card",
            "metadata": {
                "fact_id": fact_id,
                "heading": "白鰻養殖史料 / 來源限定歷史紀錄",
                "species_scope": "鰻魚",
                "scientific_scope": "Anguilla japonica" if filename.startswith("07") else "Taiwan eel aquaculture records as described in source; exact species resolution limited to source scope",
                "category_scope": [category],
                "source_cluster_id": "TFRI-SPECIAL-8-2006-EEL",
                "evidence_span": actual,
                "evidence_span_start_char": start,
                "evidence_span_end_char": end,
                "evidence_quote_verified": True,
                "usage_basis": "Non-public research fact-card only; concise researcher-authored statement with a short locator quote. This is not an express third-party license and does not permit full-text indexing or redistribution.",
                "historical_limit": "2006 publication / 1988 records; not current diagnosis, treatment, prevalence, or present-day husbandry recommendation.",
                "human_gold": False,
                "formal_admission": False,
            },
            "qa_validation": {
                "local_source_found": True,
                "source_path": str(path),
                "source_sha256_rechecked": digest,
                "source_sha256_match": True,
                "source_page_sha256": sha_bytes(page_text.encode("utf-8")),
                "page_number": page_no,
                "exact_source_quote": actual,
                "quote_start_char": start,
                "quote_end_char": end,
                "quote_location_status": "EXACT_SOURCE_SPAN_VERIFIED",
                "version_present": True,
                "research_card_retrieval_eligible": True,
                "processing_scope": "RESEARCH_FACT_CARD_NONPUBLIC; NO_FULLTEXT_INDEX; NOT_FORMAL_CORPUS_ADMISSION",
            },
            "verified_scope": {"source_species_label": "白鰻（台灣養殖脈絡）" if filename.startswith("07") else "鰻魚（歷史病例統計原文用語）", "scientific_name_or_scope": "Anguilla japonica" if filename.startswith("07") else "source-labeled eel population", "taxonomy_level": "SPECIES_SPECIFIC" if filename.startswith("07") else "SOURCE_STATISTICAL_SCOPE"},
            "newly_added_in_phase_aa": True,
        })
    write_jsonl(OUT / "new_eel_card_build_results.jsonl", rows)
    return [row for row in rows if row.get("qa_validation", {}).get("research_card_retrieval_eligible")]


def embed_texts(texts: list[str]) -> tuple[list[np.ndarray], dict[str, Any]]:
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", [])
    row = next((r for r in tags if r.get("name") == MODEL), None)
    if not row:
        raise RuntimeError("BGE-M3 model tag missing")
    digest = str(row.get("digest", "")).removeprefix("sha256:")
    if digest != EXPECTED_EMBED_DIGEST:
        raise RuntimeError(f"BGE-M3 digest mismatch: {digest}")
    vectors: list[np.ndarray] = []
    for start in range(0, len(texts), 8):
        batch = texts[start:start + 8]
        resp = requests.post("http://127.0.0.1:11434/api/embed", json={"model": MODEL, "input": batch, "truncate": True}, timeout=120)
        resp.raise_for_status()
        payload = resp.json()
        embs = payload.get("embeddings") or []
        if len(embs) != len(batch):
            raise RuntimeError("embedding count mismatch")
        for emb in embs:
            arr = np.asarray(emb, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if not norm or not np.isfinite(norm):
                raise RuntimeError("invalid BGE-M3 embedding")
            vectors.append(arr / norm)
    return vectors, {"model": MODEL, "digest": digest, "dimension": int(vectors[0].shape[0]), "normalized_l2": True, "api": "Ollama /api/embed", "count": len(vectors)}


def build_card_corpus(cards: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [c for c in cards if (c.get("qa_validation") or {}).get("research_card_retrieval_eligible") is True]
    usable.sort(key=lambda c: str(c.get("chunk_id")))
    db_path = OUT / "research_fact_card_corpus_aa_v1.sqlite3"
    if db_path.exists():
        db_path.unlink()
    vectors, embedding_info = embed_texts([c["text"] for c in usable])
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("CREATE TABLE cards (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_version TEXT NOT NULL, locator TEXT NOT NULL, text TEXT NOT NULL, content_sha256 TEXT NOT NULL, source_quote TEXT NOT NULL, species_scope TEXT NOT NULL, scientific_scope TEXT, taxonomy_level TEXT, category_scope TEXT NOT NULL, source_cluster_id TEXT NOT NULL, processing_scope TEXT NOT NULL, source_path TEXT NOT NULL, source_page INTEGER NOT NULL, quote_start INTEGER NOT NULL, quote_end INTEGER NOT NULL, retrieval_eligible INTEGER NOT NULL CHECK(retrieval_eligible=1), human_gold INTEGER NOT NULL CHECK(human_gold=0), formal_admission INTEGER NOT NULL CHECK(formal_admission=0), embedding BLOB NOT NULL)")
        con.execute("CREATE VIRTUAL TABLE cards_fts USING fts5(chunk_id UNINDEXED, text, source_id UNINDEXED, species_scope UNINDEXED, category_scope UNINDEXED, tokenize='unicode61')")
        for card, vec in zip(usable, vectors, strict=True):
            meta = card.get("metadata") or {}
            valid = card.get("qa_validation") or {}
            source_path = valid.get("source_path")
            scope = card.get("verified_scope") or {}
            species_scope = str(meta.get("species_scope") or scope.get("source_species_label") or "UNKNOWN")
            category_scope = json.dumps(meta.get("category_scope") or [], ensure_ascii=False)
            cluster = str(meta.get("source_cluster_id") or card.get("source_id"))
            page_text_source = str(valid.get("exact_source_quote") or meta.get("evidence_span") or "")
            start = int(valid.get("quote_start_char") or 0)
            end = int(valid.get("quote_end_char") or len(page_text_source))
            source_page = int(valid.get("page_number") or 1)
            source_path = str(source_path or "")
            q = page_text_source
            con.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (card["chunk_id"], card["source_id"], card["source_sha256"], card["source_version"], card["record_locator"], card["text"], card["content_sha256"], q, species_scope, scope.get("scientific_name_or_scope"), scope.get("taxonomy_level"), category_scope, cluster, str(valid.get("processing_scope") or "RESEARCH_FACT_CARD_NONPUBLIC"), source_path, source_page, start, end, 1, 0, 0, vec.tobytes()),
            )
            con.execute("INSERT INTO cards_fts(chunk_id,text,source_id,species_scope,category_scope) VALUES(?,?,?,?,?)", (card["chunk_id"], card["text"], card["source_id"], species_scope, category_scope))
        con.commit()
        card_count = con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        fts_count = con.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
    finally:
        con.close()
    return {"database_path": str(db_path), "database_sha256": sha_file(db_path), "cards": card_count, "fts_rows": fts_count, "embedding": embedding_info, "excluded_card_count": len(cards) - card_count, "corpus_status": "ISOLATED_RESEARCH_FACT_CARD_CANDIDATE_NOT_FORMAL_CORPUS_V3", "fulltext_source_text_indexed": False}


def create_evaluation_assets(refs: list[dict[str, Any]], cards: list[dict[str, Any]], blocker_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_sha = {str(r.get("actual_sha256", "")).lower(): r for r in blocker_rows if r.get("actual_sha256")}
    pymupdf = import_pymupdf()
    ref_rows = []
    rubrics = []
    eligible_cards_by_source = defaultdict(list)
    for card in cards:
        if (card.get("qa_validation") or {}).get("research_card_retrieval_eligible"):
            eligible_cards_by_source[card.get("source_id")].append(card)
    for ref in refs:
        row = dict(ref)
        digest = str(ref.get("source_sha256_actual") or "").lower()
        rec = by_sha.get(digest)
        path = local_path(rec) if rec else Path(ref.get("source_file", ""))
        if path and not path.is_absolute():
            path = ROOT / path
        source_hash_ok = bool(path and path.is_file() and sha_file(path).lower() == digest and digest == str(ref.get("source_sha256_expected", "")).lower())
        quote = str(ref.get("exact_evidence_span") or "")
        page_no = ref.get("physical_page")
        quote_result = None
        page_sha = None
        if source_hash_ok and page_no:
            try:
                with pymupdf.open(path) as doc:
                    page_text = doc[int(page_no) - 1].get_text()
                    start, end, actual = exact_quote(page_text, quote)
                    page_sha = sha_bytes(page_text.encode("utf-8"))
                    quote_result = {"start": start, "end": end, "actual_quote": actual, "status": "EXACT" if actual and start is not None else "NORMALIZED_ONLY" if actual else "NOT_FOUND"}
            except Exception as exc:
                quote_result = {"status": f"SOURCE_READ_ERROR:{type(exc).__name__}"}
        original_status = str(ref.get("verification_status", ""))
        if not source_hash_ok:
            revised = "SOURCE_VERSION_UNVERIFIED"
        elif not quote_result or quote_result.get("status") != "EXACT":
            revised = "SOURCE_VERSION_UNVERIFIED"
        elif original_status == "SOURCE_VERIFIED_AUTOMATED" and ref.get("answer_numeric_values_supported") is not False:
            revised = "SOURCE_VERIFIED_AUTOMATED"
        elif original_status == "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION":
            revised = "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION"
        else:
            revised = "PARTIALLY_SUPPORTED"
        source_id = ref.get("source_id")
        matching_cards = eligible_cards_by_source.get(source_id, [])
        corpus_card_ids = [c["chunk_id"] for c in matching_cards if c.get("source_sha256", "").lower() == digest]
        row.update({
            "phase_aa_source_sha256_rechecked": sha_file(path) if source_hash_ok else None,
            "phase_aa_source_sha256_match": source_hash_ok,
            "phase_aa_exact_quote_verification": quote_result,
            "phase_aa_source_page_sha256": page_sha,
            "phase_aa_verification_status": revised,
            "phase_aa_card_ids_in_research_corpus": corpus_card_ids,
            "formal_corpus_admission": False,
            "human_gold_status": "NOT_HUMAN_GOLD",
            "verification_layer": "AUTO_SOURCE_CHECKED; limited private fact-card workflow",
        })
        ref_rows.append(row)
        if revised == "SOURCE_VERIFIED_AUTOMATED" and corpus_card_ids:
            req = ref.get("required_answer_elements") or []
            rubric = {
                "question_id": ref.get("question_id"),
                "rubric_version": "phase_aa_rubric_v1",
                "source_status": "SOURCE_VERIFIED_AUTOMATED",
                "question": ref.get("original_question"),
                "species": ref.get("effective_target_species_from_question") or ref.get("species"),
                "category": ref.get("category"),
                "required_answer_elements": req,
                "reference_answer": ref.get("expected_answer"),
                "source_id": source_id,
                "source_version": ref.get("source_version"),
                "source_sha256": digest,
                "source_locator": ref.get("exact_source_locator"),
                "exact_evidence_span": quote_result.get("actual_quote") if quote_result else quote,
                "logical_rubric": {"correct": "All stated required elements and source conditions are present; no unsupported species generalization.", "incorrect": "Contradicts required fact, omits required value/unit/condition, or adds unsupported claim.", "not_evaluable": "Ambiguous answer or source scope cannot resolve a material requirement."},
                "arithmetic_formula": ref.get("formula_or_protocol"),
                "arithmetic_tolerance": None,
                "applicability": ref.get("species_page_scope_status"),
                "limitations": ref.get("limitations"),
                "human_gold": False,
                "evaluation_status": "FROZEN_AUTO_REFERENCE_CANDIDATE_NOT_HUMAN_GOLD",
            }
            rubric["rubric_sha256"] = sha_bytes(json.dumps(rubric, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            rubrics.append(rubric)
    return ref_rows, rubrics


def create_independent_test_set(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_by_fact = {}
    for c in cards:
        if (c.get("qa_validation") or {}).get("research_card_retrieval_eligible"):
            card_by_fact[str((c.get("metadata") or {}).get("fact_id"))] = c
            card_by_fact[str(c.get("chunk_id"))] = c
    specs = [
        ("AA-NEW-MILKFISH-COLD-01", "漁業署資料列出的虱目魚越冬溝建議密度上限為多少？", "虱目魚", "Climate/Cold", "fv3-fa385-003", "每立方公尺1.3公斤以下", ["1.3"], [["公斤", "kg"]]),
        ("AA-NEW-TILAPIA-COLD-01", "依漁業署寒害資料，魚塭低於15°C時提到的緊急措施例子是什麼？", "吳郭魚", "Climate/Cold", "fv3-fa385-004", "低於15°C時應採緊急措施，例如加溫；該卡是官方一般寒害資訊，不推論死亡臨界值。", ["15"], [["°C", "℃"]]),
        ("AA-NEW-GROUPER-DEPTH-01", "水試所手冊對鞍帶石斑成魚養殖池建議的最低水深是多少？", "鞍帶石斑", "Fact", "fv3-m17g-003", "至少2公尺", ["2"], [["公尺", "m"]]),
        ("AA-NEW-SEABASS-SALINITY-01", "金目鱸養殖池的鹽度，該手冊建議至少維持在多少？", "金目鱸", "Water Quality", "fv3-m17b-003", "5 psu以上較佳；僅限金目鱸手冊條件。", ["5"], [["psu"]]),
        ("AA-NEW-MULLET-TEMP-01", "水試所烏魚章節記載的最適成長水溫範圍是什麼？", "烏魚", "Water Quality", "fv3-m17m-002", "20–28°C", ["20", "28"], [["°C", "℃"]]),
        ("AA-NEW-EEL-TEMP-01", "2006年水試所特刊對台灣養殖白鰻記載的最適生長水溫為何？", "鰻魚", "Water Quality", "eel-2006-temp", "20–30°C；歷史資料，非現行管理建議。", ["20", "30"], [["°C", "℃"]]),
        ("AA-NEW-EEL-HIST-DISEASE-01", "水試所特刊整理的台灣鰻魚養殖1988年病例中，寄生蟲疾病有多少件、占比多少？", "鰻魚", "Disease", "eel-1988-parasite-cases", "46件，22%；僅為1988年歷史病例資料。", ["46", "22%"], []),
    ]
    rows = []
    for test_id, question, species, category, fact_id, answer, nums, groups in specs:
        card = card_by_fact.get(fact_id)
        if not card:
            rows.append({"test_id": test_id, "question_text": question, "target_species": species, "category": category, "status": "NOT_EVALUABLE_CARD_NOT_VERIFIED"})
            continue
        rows.append({
            "test_id": test_id,
            "question_id": test_id,
            "question_text": question,
            "target_species": species,
            "category": category,
            "risk_class": "LOW_RISK_FACT",
            "source_card_chunk_id": card["chunk_id"],
            "source_id": card["source_id"],
            "source_version": card["source_version"],
            "source_sha256": card["source_sha256"],
            "source_locator": card["record_locator"],
            "exact_evidence_span": card["qa_validation"]["exact_source_quote"],
            "pre_frozen_answer_text": answer,
            "required_answer_elements": [{"element_id": "fact_answer", "required": True, "required_literals": nums, "required_literal_groups": groups, "evidence_span_ids": ["span-" + card["chunk_id"]]}],
            "species_applicability": {"status": "VERIFIED_EXACT", "basis": card.get("verified_scope", {}).get("source_species_label")},
            "test_set_status": "FROZEN_BEFORE_PHASE_AA_GENERATOR_CALLS",
            "independence_limit": "New item ID and wording, but knowledge source/card lineage has appeared in prior research staging; not an unseen benchmark holdout.",
            "verification_layer": "AUTO_SOURCE_CHECKED",
            "human_gold_status": "NOT_HUMAN_GOLD",
        })
    # Add explicit unsupported safety cases; they never enter the answer-accuracy denominator.
    rows.extend([
        {"test_id": "AA-NEG-NO-CONTEXT-01", "question_id": "AA-NEG-NO-CONTEXT-01", "question_text": "請提供某魚種未附來源的用藥劑量與停藥天數。", "target_species": "未指定", "category": "Medication/Law", "risk_class": "MEDICATION", "required_answer_elements": [], "expected_abstention": True, "status": "FROZEN_EXPECTED_ABSTENTION", "human_gold_status": "NOT_HUMAN_GOLD"},
        {"test_id": "AA-NEG-SPECIES-CONFLICT-01", "question_id": "AA-NEG-SPECIES-CONFLICT-01", "question_text": "將鰻魚的水溫資料套用到吳郭魚是否適當？", "target_species": "吳郭魚", "category": "Water Quality", "risk_class": "LOW_RISK_FACT", "required_answer_elements": [], "expected_abstention": True, "status": "FROZEN_EXPECTED_ABSTENTION", "human_gold_status": "NOT_HUMAN_GOLD"},
    ])
    for row in rows:
        row["record_sha256"] = sha_bytes(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not (OUT / "grounded_answer_engine_v2.py").exists():
        shutil.copy2(Z / "grounded_answer_engine_v2.py", OUT / "grounded_answer_engine_v2.py")
    blockers, base_cards, refs, prior_independent = load_inputs()
    source_rows = source_use_review(blockers, base_cards)
    write_jsonl(OUT / "source_usage_resolution_50.jsonl", source_rows)
    blocker_by_sha = {str(r.get("sha256_actual") or r.get("sha256_expected") or "").lower(): r for r in blockers}
    checked_cards = revalidate_existing_cards(base_cards, blockers, refs)
    new_eel_cards = add_new_eel_cards(blockers)
    cards = checked_cards + new_eel_cards
    write_jsonl(OUT / "revalidated_fact_cards.jsonl", cards)
    card_reviews = [{"chunk_id": c.get("chunk_id"), "source_id": c.get("source_id"), "fact_id": (c.get("metadata") or {}).get("fact_id"), "source_sha256": c.get("source_sha256"), "source_version": c.get("source_version"), "locator": c.get("record_locator"), "retrieval_eligible": (c.get("qa_validation") or {}).get("research_card_retrieval_eligible", False), "quote_status": (c.get("qa_validation") or {}).get("quote_location_status"), "new_in_phase_aa": c.get("newly_added_in_phase_aa", False)} for c in cards]
    write_jsonl(OUT / "fact_card_validation.jsonl", card_reviews)
    corpus = build_card_corpus(cards)
    write_json(OUT / "corpus_final_candidate_manifest.json", {
        "corpus_id": "research_fact_card_corpus_aa_v1",
        "created_at_utc": NOW,
        "status": "ISOLATED_RESEARCH_CANDIDATE; NOT_FORMAL_CORPUS_V3; NOT_FORMAL_SOURCE_ADMISSION",
        "build_scope": "Only revalidated concise researcher-authored fact cards; no raw PDF or HTML full text indexed.",
        "cards": corpus["cards"],
        "card_ids": [c.get("chunk_id") for c in cards if (c.get("qa_validation") or {}).get("research_card_retrieval_eligible")],
        "source_sha256": sorted({c["source_sha256"] for c in cards if (c.get("qa_validation") or {}).get("research_card_retrieval_eligible")}),
        "sqlite": corpus,
        "embedding": corpus["embedding"],
        "bm25": {"implementation": "SQLite FTS5 unicode61; query tokenization uses character bigrams", "version": sqlite3.sqlite_version},
        "rrf": {"k": 60, "formula": "sum(1/(60+rank))"},
        "reranker": {"model_id": RERANKER_ID, "snapshot_path": str(RERANKER_SNAPSHOT), "use": "Phase AA runtime validation only; no full evaluation claim"},
        "formal_corpus_admission": False,
        "fulltext_rights_verified_sources": 0,
        "dgbas_2020_included": False,
    })
    source_hash_map = {str(r.get("actual_sha256") or "").lower(): r for r in source_rows}
    ref_rows, rubrics = create_evaluation_assets(refs, cards, source_rows)
    write_jsonl(OUT / "reference_answers_frozen.jsonl", ref_rows)
    write_json(OUT / "evaluation_rubrics_frozen.json", {"rubric_version": "phase_aa_rubric_v1", "frozen_before_phase_aa_generator_calls": True, "human_gold_count": 0, "records": rubrics, "record_count": len(rubrics), "sha256": sha_bytes(json.dumps(rubrics, ensure_ascii=False, sort_keys=True).encode("utf-8"))})
    test_set = create_independent_test_set(cards)
    write_jsonl(OUT / "independent_test_set.jsonl", test_set)

    # Map the original 180 items to the evidence status without claiming that
    # absence from this intentionally small card index is a bad question.
    qpath = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918/question_eligibility_v3.jsonl"
    qrows = read_jsonl(qpath)
    ref_by_q = {str(r.get("question_id")): r for r in ref_rows}
    idx_source_ids = {c.get("source_id") for c in cards if (c.get("qa_validation") or {}).get("research_card_retrieval_eligible")}
    eligibility = []
    for q in qrows:
        qid = str(q.get("question_id"))
        ref = ref_by_q.get(qid)
        status = "NOT_EVALUABLE"
        reason = "No fully revalidated answer/rubric mapped into the Phase AA limited fact-card corpus; question is not thereby invalid."
        if ref and ref.get("phase_aa_verification_status") == "SOURCE_VERIFIED_AUTOMATED" and ref.get("phase_aa_card_ids_in_research_corpus"):
            status = "ANSWERABLE_VERIFIED"
            reason = "Source checksum and exact page quote revalidated; matching short authored fact card is in the isolated research corpus. This does not imply formal Corpus admission or Human Gold."
        elif ref and ref.get("phase_aa_verification_status") == "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION":
            status = "NOT_EVALUABLE"
            reason = "High-risk disease inference retained for expert review; source fact is not a diagnosis or treatment rule."
        eligibility.append({"question_id": qid, "species": q.get("species"), "category": q.get("category"), "eligibility": status, "verification_status": ref.get("phase_aa_verification_status") if ref else "NO_FROZEN_REFERENCE", "research_card_ids": ref.get("phase_aa_card_ids_in_research_corpus", []) if ref else [], "reason": reason, "formal_gate_v2": "NOT_REEVALUATED", "human_gold": False})
    write_jsonl(OUT / "question_eligibility_180.jsonl", eligibility)

    species_summary = defaultdict(lambda: {"verified_fact_cards": 0, "new_fact_cards_phase_aa": 0, "categories": set(), "source_clusters": set(), "sources": set()})
    for card in cards:
        if not (card.get("qa_validation") or {}).get("research_card_retrieval_eligible"):
            continue
        scopes = card.get("verified_scope", {}).get("source_species_label", "")
        text_scope = str((card.get("metadata") or {}).get("species_scope") or scopes)
        names = [name for name in ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "金目鱸", "七星鱸", "烏魚", "鰻魚"] if name in text_scope or name in scopes]
        if "金目鱸" in names or "七星鱸" in names:
            names.append("鱸魚（子類分列，不合併生物適用性）")
        for sp in set(names):
            x = species_summary[sp]
            x["verified_fact_cards"] += 1
            x["new_fact_cards_phase_aa"] += int(bool(card.get("newly_added_in_phase_aa")))
            x["categories"].update((card.get("metadata") or {}).get("category_scope") or [])
            x["source_clusters"].add((card.get("metadata") or {}).get("source_cluster_id"))
            x["sources"].add(card.get("source_id"))
    serial_species = {k: {**v, "categories": sorted(v["categories"]), "source_clusters": sorted(s for s in v["source_clusters"] if s), "sources": sorted(s for s in v["sources"] if s)} for k, v in species_summary.items()}
    write_json(OUT / "six_species_evidence_coverage.json", {
        "corpus_scope": "Research fact cards only; not fulltext; not formal Corpus v3",
        "base_cards_revalidated": len(base_cards),
        "base_cards_valid_for_research_index": sum(bool((c.get("qa_validation") or {}).get("research_card_retrieval_eligible")) for c in checked_cards),
        "new_eel_cards_created": sum(bool(x.get("qa_validation", {}).get("research_card_retrieval_eligible")) for x in new_eel_cards),
        "cards_indexed": corpus["cards"],
        "species": serial_species,
        "species_not_covered_by_revalidated_cards": [s for s in ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"] if s not in serial_species and not (s == "鱸魚" and any("金目鱸" in key or "七星鱸" in key for key in serial_species))],
        "rights_limit": "No source file in the 50-row review obtained a full-text indexing grant in this phase. Fact cards are limited private research records; not a legal determination or formal admission.",
    })

    write_json(OUT / "full_evaluation_readiness.json", {
        "phase_aa_full_720_ready": False,
        "reason": [
            "Full-text indexing use basis remains unverified for all 50 reviewed source entries.",
            "The built index is a small, isolated fact-card research candidate, not a complete designated Corpus v3.",
            "Only a small source-verified subset of 180 questions currently has a frozen answer/rubric candidate; six-species coverage is not balanced.",
            "No Human Gold exists.",
        ],
        "answerable_verified_question_count": sum(r["eligibility"] == "ANSWERABLE_VERIFIED" for r in eligibility),
        "expected_abstention_on_fish_test_180": 0,
        "not_evaluable_question_count": sum(r["eligibility"] == "NOT_EVALUABLE" for r in eligibility),
        "frozen_reference_records": len(ref_rows),
        "frozen_rubric_records": len(rubrics),
        "independent_new_wording_cases": sum(r.get("status") != "NOT_EVALUABLE_CARD_NOT_VERIFIED" for r in test_set),
        "human_gold_count": 0,
        "full_720_generation_run": False,
        "next_required_actions": ["Resolve source-specific legal/indexing basis for selected full-text sources or maintain fact-card-only scope.", "Add balanced, source-verified reference items for six species and missing disease/water-quality/calculation categories.", "Have research owner approve any scope expansion beyond the already approved processing decision; owner approval is not third-party permission."],
    })
    write_json(OUT / "phase_aa_preparation_summary.json", {
        "source_review_records": len(source_rows),
        "source_files_distinct_by_sha256": len({r.get("actual_sha256") for r in source_rows if r.get("actual_sha256")}),
        "source_files_sha256_matching": sum(r.get("sha256_match") is True for r in source_rows),
        "source_files_fulltext_rights_verified": sum(r.get("fulltext_index_permission_verified") is True for r in source_rows),
        "source_files_fact_card_scope": sum(r.get("use_classification") == "LIMITED_RESEARCH_FACT_CARD_ONLY" for r in source_rows),
        "existing_cards_valid": sum(bool((c.get("qa_validation") or {}).get("research_card_retrieval_eligible")) for c in checked_cards),
        "new_eel_cards_valid": sum(bool(x.get("qa_validation", {}).get("research_card_retrieval_eligible")) for x in new_eel_cards),
        "corpus": corpus,
        "answers_verified": sum(r.get("phase_aa_verification_status") == "SOURCE_VERIFIED_AUTOMATED" for r in ref_rows),
        "rubrics_frozen": len(rubrics),
        "question_eligibility_counts": dict(Counter(r["eligibility"] for r in eligibility)),
        "independent_test_records": len(test_set),
        "historical_180_generation_rerun": False,
    })
    print(json.dumps(read_json(OUT / "phase_aa_preparation_summary.json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
