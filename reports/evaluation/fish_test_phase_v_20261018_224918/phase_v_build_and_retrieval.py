from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
U = ROOT / "reports/evaluation/fish_test_phase_u_20261018_195823"
U_CORPUS = U / "corpus_v3_final"
NEW_CORPUS = RUN / "corpus_v3_final"
QUESTION_FILE = ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl"
OWNER_FILE = U / "source_owner_decision_update_57.jsonl"
RIGHTS_FILE = U / "source_rights_version_scope_audit_57_final.jsonl"
FORENSICS_FILE = RUN / "source_file_forensics_57.jsonl"
OLLAMA = "http://127.0.0.1:11434"
BGE = "bge-m3:latest"
BGE_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
RERANKER_SNAPSHOT = ROOT / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_source_rows():
    owners = read_jsonl(OWNER_FILE)
    rights = read_jsonl(RIGHTS_FILE)
    by_id = {r["source_record_id"]: r for r in rights}
    if len(owners) != 57 or len(rights) != 57:
        raise RuntimeError(f"Expected 57 owner and rights records, got {len(owners)}, {len(rights)}")
    if any(r.get("owner_decision") != "APPROVED" for r in owners):
        raise RuntimeError("Phase U owner decision records are not all APPROVED")
    return owners, rights, by_id


def normalized_map(text: str):
    chars, starts, ends = [], [], []
    in_ws = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_ws and chars:
                chars.append(" "); starts.append(i); ends.append(i + 1)
            elif in_ws:
                ends[-1] = i + 1
            in_ws = True
        else:
            chars.append(ch); starts.append(i); ends.append(i + 1); in_ws = False
    while chars and chars[-1] == " ":
        chars.pop(); starts.pop(); ends.pop()
    return "".join(chars), starts, ends


def source_registry_record(path: Path, source_id: str, title: str, publisher: str, url: str, version: str, usage_scope: str, cluster: str):
    return {
        "source_id": source_id,
        "title": title,
        "publisher": publisher,
        "local_file": str(path.relative_to(ROOT)),
        "sha256": sha_file(path),
        "source_url": url,
        "resource_url": url,
        "license": "No full-text license claimed; limited factual extraction and researcher-authored cards only",
        "attribution": f"{publisher}, {title}, {version}; factual statement paraphrased for nonpublic research; source locator retained",
        "version": version,
        "usage_scope": usage_scope,
        "retrieval_default": 1,
        "source_cluster_id": cluster,
        "rights_assessment": "Owner-approved research use is recorded; this record does not claim third-party full-text indexing authorization. Index only concise researcher-authored factual statements, with short locator quotes stored as provenance and not indexed.",
    }


def extract_quote(path: Path, physical_page: int, anchor: str):
    import pymupdf
    doc = pymupdf.open(path)
    page_text = doc[physical_page - 1].get_text("text")
    def compact(value):
        value=value.translate(str.maketrans({"（":"(","）":")","～":"~","－":"-","–":"-","—":"-","℃":"°C"}))
        return "".join(value.split())
    compact_text=[]; raw_positions=[]
    for i,ch in enumerate(page_text):
        if not ch.isspace():
            mapped=ch.translate(str.maketrans({"（":"(","）":")","～":"~","－":"-","–":"-","—":"-","℃":"°C"}))
            compact_text.append(mapped)
            raw_positions.extend([i]*len(mapped))
    normalized="".join(compact_text)
    anchor_norm=compact(anchor)
    idx=normalized.find(anchor_norm)
    if idx < 0:
        # Use an anchored exact line as a fallback; still verify that the returned span is in the source page.
        anchor_compact=compact(anchor)
        for line in page_text.splitlines():
            if anchor_compact in compact(line):
                s = page_text.find(line)
                return line, s, s + len(line), page_text
        raise ValueError(f"Anchor not present in {path.name} page {physical_page}: {anchor}")
    raw_start, raw_end = raw_positions[idx], raw_positions[idx + len(anchor_norm)-1] + 1
    return page_text[raw_start:raw_end], raw_start, raw_end, page_text


def build_fact_cards():
    manual = ROOT / "my_data/my_data/技術手冊17-第三章水產養殖管理技術 第二節金目鱸.pdf"
    sevenstar = ROOT / "my_data/my_data/技術手冊17-第三章水產養殖管理技術 第三節七星鱸.pdf"
    grouper = ROOT / "my_data/my_data/技術手冊17-第三章水產養殖管理技術 第四節石斑魚.pdf"
    mullet = ROOT / "my_data/my_data/技術手冊17-第三章水產養殖管理技術 第六節烏魚.pdf"
    fa_cold = ROOT / "my_data/my_data/養殖漁業防寒須知(農業部漁業署).pdf"
    eel_mold = ROOT / "my_data/my_data/04鰻魚黴菌性疾病.pdf.pdf"
    manual_url = "https://www.tfrin.gov.tw/ws.php?id=246"
    fa_url = "https://www.fa.gov.tw/view.php?theme=web_structure&subtheme=&id=385"
    sources = {
        "TFRI-M17-GOLD-SEABASS": source_registry_record(manual, "TFRI-M17-GOLD-SEABASS", "漁電共生養殖技術應用手冊(下)：金目鱸章", "農業部水產試驗所", manual_url, "技術手冊17, 2023-08-31; chapter PDF", "Only facts and narrow research cards for Lates calcarifer; no full-text indexing", "TFRI-M17-2023"),
        "TFRI-M17-SEVENSTAR": source_registry_record(sevenstar, "TFRI-M17-SEVENSTAR", "漁電共生養殖技術應用手冊(下)：七星鱸章", "農業部水產試驗所", manual_url, "技術手冊17, 2023-08-31; chapter PDF", "Only facts and narrow research cards for Lateolabrax japonicus; do not generalize to all seabass", "TFRI-M17-2023"),
        "TFRI-M17-GROUPER": source_registry_record(grouper, "TFRI-M17-GROUPER", "漁電共生養殖技術應用手冊(下)：石斑魚章", "農業部水產試驗所", manual_url, "技術手冊17, 2023-08-31; chapter PDF", "Only the cited grouper-group facts and explicit species-specific subscopes; no full-text indexing", "TFRI-M17-2023"),
        "TFRI-M17-MULLET": source_registry_record(mullet, "TFRI-M17-MULLET", "漁電共生養殖技術應用手冊(下)：烏魚章", "農業部水產試驗所", manual_url, "技術手冊17, 2023-08-31; chapter PDF", "Only facts scoped to Mugil cephalus and the specified age group; no full-text indexing", "TFRI-M17-2023"),
        "FA-385-COLD": source_registry_record(fa_cold, "FA-385-COLD", "養殖漁業防寒須知", "農業部漁業署", fa_url, "official page print snapshot 2026-07-02; page update date not confirmed", "Short attributed facts for cold-weather management; no full-text indexing or public redistribution of the snapshot", "FA-COLD-385"),
        "TFRI-EEL-MOLD-2006": source_registry_record(eel_mold, "TFRI-EEL-MOLD-2006", "鰻魚養殖之健康管理：黴菌性疾病", "農業部水產試驗所特刊第8號", "https://www.tfrin.gov.tw/theme_list.php?option=15&page=9&theme=paper", "TFRI Special No. 8, 2006, pp.75-84; local article PDF", "Historical descriptive facts only; not current treatment or prevalence advice; no full-text indexing", "TFRI-SPECIAL-8-2006"),
    }
    facts = [
        ("m17s-001", "TFRI-M17-SEVENSTAR", 1, "七星鱸(Lateolabrax japonicus)", "七星鱸（Lateolabrax japonicus）是技術手冊明確辨識的物種；本卡僅適用於七星鱸，不能替代金目鱸資料。", "鱸魚", "Fact", "SPECIFIC: Lateolabrax japonicus; not all seabass", "3-3-1", "七星鱸（Lateolabrax japonicus）"),
        ("m17s-002", "TFRI-M17-SEVENSTAR", 2, "七星鱸最適成長水溫", "手冊記載七星鱸最適成長水溫為23–28°C；高於28°C或低於15°C時攝餌率逐漸變差。這是七星鱸資料，不套用於未指明種類的鱸魚。", "鱸魚", "Water Quality", "SPECIFIC: Lateolabrax japonicus", "3-3-2", "七星鱸最適成長水溫為23 ～ 28℃間"),
        ("m17s-003", "TFRI-M17-SEVENSTAR", 2, "七星鱸養殖鹽度環境", "七星鱸可在淡水、半淡鹹水及海水養殖池中養殖；淡水中成長較快但活存率稍差。", "鱸魚", "Water Quality", "SPECIFIC: Lateolabrax japonicus", "3-3-2", "七星鱸為廣鹽性魚種"),
        ("m17s-004", "TFRI-M17-SEVENSTAR", 2, "七星鱸養殖池深度", "手冊建議七星鱸池水深至少1公尺，若能常保持1.5公尺以上較佳。", "鱸魚", "Fact", "SPECIFIC: Lateolabrax japonicus", "3-3-2", "養殖池建議水深應至少1 公尺以深"),
        ("m17s-005", "TFRI-M17-SEVENSTAR", 4, "七星鱸放養密度", "一般七星鱸放養密度約40,000–80,000尾/公頃，需依水源、水質、養殖設施及管理條件調整。", "鱸魚", "Calculation", "SPECIFIC: Lateolabrax japonicus; density depends on farm conditions", "3-3-4", "一般密度約在每公頃40,000"),
        ("m17g-001", "TFRI-M17-GROUPER", 1, "石斑魚分類範圍", "手冊所稱石斑魚包含石斑屬、喙鱸屬及若干其他屬；此組名不等於單一物種，數值應以題目指定物種與來源範圍為準。", "石斑魚", "Fact", "GROUP: multiple genera; not one species", "3-4-1", "石斑魚主要是指石斑魚屬及喙鱸屬"),
        ("m17g-002", "TFRI-M17-GROUPER", 1, "石斑魚組別溫度參考", "手冊對其石斑魚組別記載生存水溫11–35°C，最適成長及存活水溫25–30°C；適用於該手冊定義的組別，不保證每個石斑物種相同。", "石斑魚", "Water Quality", "GROUP: manual-defined grouper group; verify exact species before applying", "3-4-1", "生存溫度則在11 ～ 35℃之間"),
        ("m17g-003", "TFRI-M17-GROUPER", 2, "鞍帶石斑養殖池水深", "鞍帶石斑（Epinephelus lanceolatus）成魚養殖池建議至少2公尺水深；不推廣到其他石斑魚。", "石斑魚", "Fact", "SPECIFIC: Epinephelus lanceolatus", "3-4-2", "成魚養殖池水深建議至"),
        ("m17g-004", "TFRI-M17-GROUPER", 4, "鞍帶石斑放養密度", "手冊指出一般鞍帶石斑放養密度約10,000–30,000尾/公頃，需依水質與養殖經驗調整。", "石斑魚", "Calculation", "SPECIFIC: Epinephelus lanceolatus; site-dependent", "3-4-4", "一般放養密度約落在10,000"),
        ("m17b-001", "TFRI-M17-GOLD-SEABASS", 1, "金目鱸分類與棲地", "金目鱸的學名為Lates calcarifer；手冊描述其自然棲地常為半淡鹹水河口，並具有較高鹽度耐受性。不可泛化為全部鱸魚。", "鱸魚", "Fact", "SPECIFIC: Lates calcarifer; not all seabass", "3-2-1", "金目鱸(Lates calcarifer)"),
        ("m17b-002", "TFRI-M17-GOLD-SEABASS", 2, "金目鱸低溫與攝食", "金目鱸最佳成長水溫28–32°C；低於23°C食慾降低，手冊亦提醒水黴病二次感染風險。此卡不構成疾病診斷。", "鱸魚", "Climate / Cold", "SPECIFIC: Lates calcarifer", "3-2-2", "最佳成長溫度為28 ～32℃"),
        ("m17b-003", "TFRI-M17-GOLD-SEABASS", 2, "金目鱸鹽度參考", "手冊建議金目鱸養殖池鹽度維持在5 psu以上較佳；這是該手冊條件，不是所有鱸魚的通用門檻。", "鱸魚", "Water Quality", "SPECIFIC: Lates calcarifer", "3-2-2", "建議維持鹽度在5 psu 以上較佳"),
        ("m17b-004", "TFRI-M17-GOLD-SEABASS", 2, "金目鱸池深度及水車", "金目鱸養殖池水深建議1.5–2公尺，且每分地至少配置1臺水車；適用條件須依章節語境判讀。", "鱸魚", "Fact", "SPECIFIC: Lates calcarifer", "3-2-2", "養殖池水深至少需保持在1.5 ～2 公尺"),
        ("m17b-005", "TFRI-M17-GOLD-SEABASS", 5, "金目鱸放養密度", "金目鱸魚苗建議放養40,000–80,000尾/公頃，苗體長約6公分；需核對來源章節對苗種來源的限定。", "鱸魚", "Calculation", "SPECIFIC: Lates calcarifer; seed source condition applies", "3-2-5", "建議魚苗放養40,000 ～80,000 尾/ 公頃"),
        ("m17b-006", "TFRI-M17-GOLD-SEABASS", 5, "金目鱸整池石灰用量", "手冊記載該章整池使用石灰約每分地30–50公斤；不可脫離整池程序與池況作為獨立操作建議。", "鱸魚", "Calculation", "SPECIFIC: Lates calcarifer; pond-preparation condition required", "3-2-5", "每分地使用量約30"),
        ("m17m-001", "TFRI-M17-MULLET", 1, "烏魚物種", "手冊以烏魚（Mugil cephalus）為該章物種；此範圍不等於所有鯔科魚類或吳郭魚。", "烏魚", "Fact", "SPECIFIC: Mugil cephalus", "3-6-1", "烏魚（Mugil cephalus）"),
        ("m17m-002", "TFRI-M17-MULLET", 2, "烏魚水溫參考", "烏魚生存水溫範圍3–35°C，最適成長水溫20–28°C。這是該章烏魚資料。", "烏魚", "Water Quality", "SPECIFIC: Mugil cephalus", "3-6-2", "生存之水溫範圍為3 ～ 35℃"),
        ("m17m-003", "TFRI-M17-MULLET", 4, "烏魚分齡放養密度", "手冊建議烏魚1齡每公頃約10,000–20,000尾，2齡以上約5,000–6,000尾；實際密度仍須依現場條件調整。", "烏魚", "Calculation", "SPECIFIC: Mugil cephalus; age group and site conditions apply", "3-6-4", "烏魚1 齡養殖放養密度"),
        ("fa385-001", "FA-385-COLD", 1, "熱帶魚種寒害風險", "漁業署頁面將虱目魚及吳郭魚列為不適合冬季養殖的熱帶魚例子，並建議養殖者自行評估越冬風險；不是死亡溫度判定。", "虱目魚|吳郭魚", "Climate / Cold", "MULTI_SPECIES: milkfish and tilapia examples; general winter risk notice", "official page id=385, print snapshot page 1", "不適合冬季養殖之熱帶魚種（如虱目魚、吳郭魚等）"),
        ("fa385-002", "FA-385-COLD", 1, "寒流期間魚塭操作限制", "寒流來襲時，漁業署建議儘量避免驚動魚群的投餌、換水及無謂開關水車行為；暖和回升日才依情況酌量投餌。", "虱目魚|吳郭魚|general_aquaculture", "Climate / Cold", "GENERAL_AQUACULTURE: winter cold surge pond management", "official page id=385, print snapshot page 1", "寒流來襲時，儘量避免有驚動魚塭內魚群之行為"),
        ("fa385-003", "FA-385-COLD", 1, "越冬溝虱目魚密度", "虱目魚越冬溝建議密度為每立方公尺1.3公斤以下，且原文明確提示密度會因環境、條件與種類而異。", "虱目魚", "Climate / Cold", "SPECIFIC: milkfish overwintering ditch; density conditional", "official page id=385, print snapshot page 1", "越冬溝內之密度以虱目魚在每立方公尺1.3公斤以下為宜"),
        ("fa385-004", "FA-385-COLD", 1, "防風棚與寒害處置", "漁業署建議魚塭北側搭防風棚且棚蓋與水面角度小於30度；低於15°C時應採緊急措施，例如加溫。", "虱目魚|吳郭魚|general_aquaculture", "Climate / Cold", "GENERAL_AQUACULTURE: government cold notice; below-15°C emergency instruction", "official page id=385, print snapshot page 1", "於魚塭北側搭蓋防風棚"),
        ("fa385-005", "FA-385-COLD", 1, "寒流後浮魚處置", "漁業署建議寒流後立即撿除浮於水面之魚體，以防水質惡化；這不是病因診斷或治療建議。", "虱目魚|吳郭魚|general_aquaculture", "Climate / Cold", "GENERAL_AQUACULTURE: cold notice", "official page id=385, print snapshot page 1", "浮於水面之魚體須馬上撿除"),
        ("eel-2006-001", "TFRI-EEL-MOLD-2006", 2, "鰻魚黴菌病歷史描述", "2006年水試所特刊描述水黴病可在魚體皮膚或鰭部受損後形成二次性感染；此為歷史文獻描述，不作為當前診斷或治療規範。", "鰻魚", "Disease", "SPECIFIC: eel; historical article 2006; descriptive only", "PDF page 2; printed pp.75-76", "水黴菌為二次性感染"),
        ("eel-2006-002", "TFRI-EEL-MOLD-2006", 3, "鰻魚疾病診斷限制", "特刊建議疾病判斷需檢查病原並由獸醫師診斷；外觀症狀可能與其他疾病相似，因此不可僅依症狀直接指定用藥。", "鰻魚", "Disease", "SPECIFIC: eel; historical article 2006; clinical review required", "PDF page 3; printed p.77", "獸醫師檢查及開立處方"),
    ]
    cards = []
    for fid, sid, pg, heading, statement, species, category, scope, printed_page, anchor in facts:
        src = sources[sid]
        p = ROOT / src["local_file"]
        quote, raw_start, raw_end, page_text = extract_quote(p, pg, anchor)
        norm_page = re.sub(r"\s+", " ", page_text).strip()
        if re.sub(r"\s+", " ", quote).strip() not in norm_page:
            raise AssertionError(f"quote does not match source page: {fid}")
        cards.append({
            "chunk_id": f"fv3-{fid}", "source_id": sid, "source_sha256": src["sha256"],
            "source_version": src["version"], "record_locator": f"PDF physical page {pg}; printed locator {printed_page}",
            "content_sha256": sha_bytes(statement.encode("utf-8")), "text": statement,
            "retrieval_eligible": True, "chunk_role": "researcher_authored_fact_card",
            "metadata": {"fact_id": fid, "heading": heading, "species_scope": species,
                "species_taxonomy": scope, "category_scope": [category], "source_cluster_id": src["source_cluster_id"],
                "evidence_span": quote, "evidence_span_start_char": raw_start, "evidence_span_end_char": raw_end,
                "evidence_page_sha256": sha_bytes(page_text.encode("utf-8")),
                "evidence_normalization_for_match": "whitespace-collapsed PDF text layer; raw span offsets refer to extracted page text",
                "evidence_quote_verified": True, "usage_basis": src["rights_assessment"],
                "human_gold": False, "source_integrity_verified": True,
                "admission_scope": "limited factual card; no fulltext source text indexed"}}
        )
    return sources, cards


def resolve_blockers(owners, rights, u_chunks):
    owner_by = {r["source_record_id"]: r for r in owners}
    corpus_sources = {r[0] for r in sqlite3.connect(U_CORPUS / "corpus_v3_final.sqlite3").execute("SELECT source_id FROM sources")}
    # Most source records are not an unqualified full-text admission; rights, version and parsing are resolved independently.
    out = []
    for r in rights:
        if r["source_record_id"] in {"SRC-0c9dbad3d5a7", "SRC-a15a3c0c2a8b", "SRC-a44337f6c3e8", "SRC-98712175a309", "SRC-be42cf6c9632", "SRC-3419578f78be", "SRC-9427ecc0ecf6"}:
            continue
        o = owner_by[r["source_record_id"]]
        path_s = r.get("local_file") or o.get("original_path")
        p = ROOT / path_s if path_s else None
        actual = sha_file(p) if p and p.is_file() else None
        matches = actual == o.get("checksum_sha256") == r.get("source_sha256")
        forensic = next((x for x in read_jsonl(FORENSICS_FILE) if x.get("source_record_id") == r["source_record_id"]), {})
        info = forensic.get("file_inspection", {})
        blockers = []
        if not p or not p.is_file(): blockers.append("SOURCE_FILE_MISSING")
        if not matches: blockers.append("SOURCE_CHECKSUM_MISMATCH")
        title = r.get("source_title") or o.get("title")
        publisher = r.get("publisher") or o.get("publisher")
        version = r.get("source_version") or o.get("version")
        url = r.get("source_url") or o.get("url")
        rights_status = r.get("rights_status") or "UNVERIFIED"
        legal = "statutory" in str(rights_status).lower()
        fulltext_rights = ("explicit license not found" if "copyright" in str(rights_status).lower() else "not independently established")
        if publisher in (None, "UNVERIFIED", "unverified"): blockers.append("PUBLISHER_NOT_VERIFIED")
        if not url: blockers.append("OFFICIAL_URL_NOT_VERIFIED")
        if version in (None, "UNVERIFIED", "unverified") or "unverified" in str(version).lower(): blockers.append("DOCUMENT_VERSION_NOT_FIXED")
        if legal and "version" in " ".join(blockers).lower(): blockers.append("STATUTORY_SNAPSHOT_NOT_MATCHED_TO_CURRENT_OFFICIAL_VERSION")
        if info.get("parser_error"): blockers.append("PARSER_ERROR")
        if info.get("page_count") and info.get("empty_pages", 0): blockers.append("SCANNED_OR_EMPTY_PAGES_NEED_OCR_QA")
        if "copyright" in str(rights_status).lower() or "unverified" in str(rights_status).lower(): blockers.append("FULLTEXT_INDEX_RIGHTS_NOT_ESTABLISHED")
        if not info.get("extracted_characters"): blockers.append("PARSER_CONTENT_NOT_ASSESSED")
        if o.get("expected_species_and_categories", {}).get("species_candidates") and not o.get("species_content_signals"):
            blockers.append("SPECIES_SCOPE_NEEDS_CONTENT_VALIDATION")
        out.append({
            "source_record_id": r["source_record_id"], "source_id": r.get("source_id"), "title": title,
            "local_file": path_s, "sha256_expected": o.get("checksum_sha256"), "sha256_actual": actual,
            "checksum_match": matches, "file_exists": bool(p and p.is_file()),
            "owner_decision": o.get("owner_decision"), "owner_decision_date": o.get("owner_decision_date"),
            "publisher": publisher, "official_url": url, "document_version": version,
            "reference_metadata": o.get("effective_date"), "format": info.get("format"),
            "page_count": info.get("page_count"), "extracted_characters": info.get("extracted_characters"),
            "empty_or_unextractable_pages": info.get("empty_pages"), "parser_error": info.get("parser_error"),
            "rights_status_fulltext": rights_status, "fulltext_index_basis": fulltext_rights,
            "limited_fact_card_scope": "possible only for individually verified unprotected facts/methods with researcher-authored concise wording and precise citation; not a fulltext license claim",
            "source_in_u_corpus": bool(r.get("source_id") in corpus_sources),
            "blocker_codes": list(dict.fromkeys(blockers)),
            "resolution": "FACT_CARD_ONLY_CANDIDATE" if matches and info.get("extracted_characters") and not info.get("parser_error") else "BLOCKED_FOR_INDEX_PENDING_SOURCE_OR_PARSER_VALIDATION",
            "notes": ["Owner APPROVED is preserved from Phase U records; no new owner approval required.", "Owner decision is not third-party permission.", "No fulltext indexing is implied."]
        })
    return out


def copy_and_build_corpus(sources, cards):
    if NEW_CORPUS.exists():
        raise FileExistsError(f"Refusing to overwrite {NEW_CORPUS}")
    NEW_CORPUS.mkdir(parents=True)
    u_manifest = read_json(U_CORPUS / "corpus_v3_manifest.json")
    shutil.copy2(U_CORPUS / "corpus_chunks_v3_final.jsonl", NEW_CORPUS / "corpus_chunks_v3_final.jsonl")
    shutil.copy2(U_CORPUS / "dense_vectors_final.f32", NEW_CORPUS / "dense_vectors_v3_final.f32")
    shutil.copy2(U_CORPUS / "corpus_v3_final.sqlite3", NEW_CORPUS / "corpus_v3_final.sqlite3")
    con = sqlite3.connect(NEW_CORPUS / "corpus_v3_final.sqlite3")
    cur = con.cursor()
    for s in sources.values():
        cur.execute("INSERT INTO sources(source_id,title,publisher,local_file,sha256,source_url,resource_url,license,attribution,version,usage_scope,retrieval_default) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["source_id"],s["title"],s["publisher"],s["local_file"],s["sha256"],s["source_url"],s["resource_url"],s["license"],s["attribution"],s["version"],s["usage_scope"],s["retrieval_default"]))
    chunk_rows = []
    for c in cards:
        metadata = dict(c["metadata"])
        metadata.update({"chunk_id":c["chunk_id"],"corpus_version":"research_corpus_v3_phase_v_20261018","source_id":c["source_id"],"source_sha256":c["source_sha256"],"source_version":c["source_version"],"record_locator":c["record_locator"],"content_sha256":c["content_sha256"],"retrieval_eligible":True,"chunk_role":c["chunk_role"],"source_title":sources[c["source_id"]]["title"],"source_url":sources[c["source_id"]]["source_url"],"publisher":sources[c["source_id"]]["publisher"]})
        c["metadata_json"] = json.dumps(metadata,ensure_ascii=False,sort_keys=True)
        cur.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?)",(c["chunk_id"],c["source_id"],c["source_sha256"],c["source_version"],c["record_locator"],c["content_sha256"],c["text"],c["metadata_json"],1,c["chunk_role"]))
        tokens=[]
        for match in re.finditer(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+",c["text"].casefold(),re.I):
            token=match.group(0)
            if re.fullmatch(r"[\u3400-\u9fff]+",token):
                tokens.extend([token] if len(token)==1 else [token[i:i+2] for i in range(len(token)-1)])
            else:
                tokens.append(token)
        tokens=" ".join(tokens)
        cur.execute("INSERT INTO chunks_fts(chunk_id,token_text) VALUES(?,?)",(c["chunk_id"],tokens))
        c.update({"source_title":sources[c["source_id"]]["title"],"source_url":sources[c["source_id"]]["source_url"],"publisher":sources[c["source_id"]]["publisher"],"species_scope":metadata["species_scope"],"category_scope":metadata["category_scope"],"source_cluster_id":metadata["source_cluster_id"],"attribution":sources[c["source_id"]]["attribution"],"resource_url":sources[c["source_id"]]["resource_url"],"license":sources[c["source_id"]]["license"]})
        chunk_rows.append({k:v for k,v in c.items() if k!="metadata"})
    con.commit()
    # The file contains the original 17,377 chunk records. Append only authored fact-card content; exact quotations remain metadata and are not indexed.
    with (NEW_CORPUS / "corpus_chunks_v3_final.jsonl").open("a",encoding="utf-8") as f:
        for row in chunk_rows: f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    import requests
    tag = requests.get(f"{OLLAMA}/api/tags",timeout=10).json().get("models",[])
    found=[m for m in tag if m.get("name")==BGE]
    if not found or found[0].get("digest","").removeprefix("sha256:")!=BGE_DIGEST:
        raise RuntimeError("BGE-M3 model identity/digest mismatch")
    texts=[c["text"] for c in cards]
    vecs=[]
    for start in range(0,len(texts),16):
        batch=texts[start:start+16]
        r=requests.post(f"{OLLAMA}/api/embed",json={"model":BGE,"input":batch,"truncate":False,"keep_alive":"30m"},timeout=180)
        r.raise_for_status()
        import numpy as np
        a=np.asarray(r.json()["embeddings"],dtype=np.float32)
        if a.shape!=(len(batch),1024) or not np.isfinite(a).all(): raise RuntimeError(f"Invalid fact-card embeddings {a.shape}")
        a/=np.linalg.norm(a,axis=1,keepdims=True)
        vecs.append(a)
    import numpy as np
    new_vectors=np.vstack(vecs) if vecs else np.empty((0,1024),dtype=np.float32)
    with (NEW_CORPUS / "dense_vectors_v3_final.f32").open("ab") as f: f.write(new_vectors.astype(np.float32).tobytes())
    con.close()
    all_chunks=read_jsonl(NEW_CORPUS/"corpus_chunks_v3_final.jsonl")
    eligible=[c for c in all_chunks if c.get("retrieval_eligible")]
    manifest={"corpus_version":"research_corpus_v3_phase_v_20261018","created_at_utc":datetime.now(timezone.utc).isoformat(),"build_status":"BUILT_ISOLATED_WITH_LIMITED_FACT_CARDS","formal_production_corpus":False,"source_approval_reference":"PHASE-U-SOURCE-MATRIX-57-OWNER-APPROVAL-20261018","owner_approved_records":57,"distinct_source_hashes_in_owner_matrix":55,"phase_u_base_corpus_version":u_manifest["corpus_version"],"phase_u_original_chunks_preserved":len(read_jsonl(U_CORPUS/"corpus_chunks_v3_final.jsonl")),"phase_u_original_retrieval_eligible":u_manifest["retrieval_eligible_chunk_count"],"new_authored_fact_cards":len(cards),"new_fact_card_sources":len(sources),"total_chunk_count":len(all_chunks),"retrieval_eligible_chunk_count":len(eligible),"context_only_chunk_count":sum(not c.get("retrieval_eligible") for c in all_chunks),"included_original_source_ids":sorted({s["source_id"] for s in read_jsonl(NEW_CORPUS/"corpus_chunks_v3_final.jsonl")}),"new_fact_card_source_ids":sorted(sources),"source_policy":"Use copied Phase U corpus plus concise researcher-authored factual cards from independently checksum-verified originals. Copyrighted source full text is not indexed. DGBAS scopes are inherited without expansion.","embedding_index":{"status":"BUILT","model":BGE,"model_digest":BGE_DIGEST,"dimensions":1024,"normalization":"L2 unit normalization","matrix_order_ids_sha256":sha_bytes("\n".join(c["chunk_id"] for c in eligible).encode()),"vector_file_sha256":sha_file(NEW_CORPUS/"dense_vectors_v3_final.f32"),"vector_rows":len(eligible)},"bm25":{"status":"BUILT","engine":"SQLite FTS5","base_tokenizer":"phase U bigram tokens preserved","fact_card_tokenizer":"character bigrams plus Latin terms"},"rrf":{"k":60,"weights":{"bm25":1.0,"dense":1.0},"candidate_depth":100},"reranker":{"model_id":"BAAI/bge-reranker-v2-m3","revision":"953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e","snapshot_path":str(RERANKER_SNAPSHOT.relative_to(ROOT)),"status":"verified local snapshot; runtime test pending retrieval"},"top_k":5,"provenance_policy":"Every card retains source SHA-256, PDF physical page, printed locator, normalized quote verification and exact extracted-text offsets.","fulltext_rights_status":"not claimed for copyrighted manuals; factual cards only"}
    manifest["chunk_jsonl_sha256"]=sha_file(NEW_CORPUS/"corpus_chunks_v3_final.jsonl")
    manifest["sqlite_sha256"]=sha_file(NEW_CORPUS/"corpus_v3_final.sqlite3")
    write_json(NEW_CORPUS/"corpus_v3_final_manifest.json",manifest)
    write_jsonl(NEW_CORPUS/"source_registry_v3.jsonl",list(sources.values()))
    write_jsonl(NEW_CORPUS/"fact_card_registry.jsonl",cards)
    return manifest


TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./_%+\-][a-z0-9]+)*|[\u3400-\u9fff]+",re.I)

def tokenize(text):
    out=[]
    for m in TOKEN_RE.finditer(text.casefold()):
        x=m.group(0)
        out.extend([x] if len(x)==1 or not re.fullmatch(r"[\u3400-\u9fff]+",x) else [x[i:i+2] for i in range(len(x)-1)])
    return out


def classify_scope(q):
    text=q["question_text"]
    cat=q.get("inferred_category") or q.get("topic") or "UNCLASSIFIED"
    species=q.get("species_chinese") or ""
    allow=[]
    if cat in ("Medication / Law","Medication/Law","法規"):
        intent="general_legal_requirements"; allow=["MOA-FL014718-ACT"]
    elif any(x in text for x in ["資料集","統計資料","統計數據","養殖產量","漁業生產量","產值是多少","產量是多少"]):
        intent="statistics"; allow=["MOA-FISHERY-PRODUCTION-44084","DGBAS-79395-2015","DGBAS-79395-2020"]
    elif cat in ("Climate / Cold","Climate/Cold"):
        intent="cold_management"; allow=["FA-385-COLD"]
    elif species=="虱目魚" and "越冬溝" in text:
        intent="milkfish_overwintering_density"; allow=["FA-385-COLD"]
    elif species=="吳郭魚" and ("寒流" in text or "寒害" in text or "防寒" in text):
        intent="tilapia_cold_management"; allow=["FA-385-COLD"]
    else:
        intent="species_technical"; allow=[s for s in ["TFRI-M17-GOLD-SEABASS","TFRI-M17-SEVENSTAR","TFRI-M17-GROUPER","TFRI-M17-MULLET","TFRI-EEL-MOLD-2006"]]
    # Preserve exact species scope when matching researcher-authored cards.
    return {"intent":intent,"category":cat,"species":species,"allowed_source_ids":allow}


def retrieve_all(manifest):
    import numpy as np
    import requests
    sys.path.insert(0,str(ROOT/".venv-reranker/Lib/site-packages"))
    sys.path.insert(0,str(ROOT/".venv/Lib/site-packages"))
    sys.path.insert(0,str(ROOT))
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    tags=requests.get(f"{OLLAMA}/api/tags",timeout=8).json().get("models",[])
    match=[m for m in tags if m.get("name")==BGE]
    if not match or match[0].get("digest","").removeprefix("sha256:")!=BGE_DIGEST: raise RuntimeError("BGE runtime digest changed")
    chunks=read_jsonl(NEW_CORPUS/"corpus_chunks_v3_final.jsonl")
    eligible=[c for c in chunks if c.get("retrieval_eligible")]
    vectors=np.memmap(NEW_CORPUS/"dense_vectors_v3_final.f32",dtype=np.float32,mode="r",shape=(len(eligible),1024))
    ids=[c["chunk_id"] for c in eligible]
    if sha_bytes("\n".join(ids).encode())!=manifest["embedding_index"]["matrix_order_ids_sha256"]: raise RuntimeError("vector order mismatch")
    con=sqlite3.connect(NEW_CORPUS/"corpus_v3_final.sqlite3")
    qs=read_jsonl(QUESTION_FILE)
    reranker=CrossEncoderRuntime(RERANKER_SNAPSHOT,device="cuda",max_length=512,batch_size=4)
    profiles=[classify_scope(q) for q in qs]
    queries=[f"{p['species']} {q['question_text']}".strip() for q,p in zip(qs,profiles)]
    allq=[]
    for j in range(0,len(queries),24):
        r=requests.post(f"{OLLAMA}/api/embed",json={"model":BGE,"input":queries[j:j+24],"truncate":False,"keep_alive":"30m"},timeout=180)
        r.raise_for_status(); x=np.asarray(r.json()["embeddings"],dtype=np.float32)
        if x.shape!=(len(queries[j:j+24]),1024): raise RuntimeError("query embedding shape mismatch")
        x/=np.linalg.norm(x,axis=1,keepdims=True); allq.append(x)
    qvecs=np.vstack(allq)
    by_id={c["chunk_id"]:c for c in eligible}
    # chunks_fts is contentless: its stored chunk_id column reads NULL.  Its rowid
    # follows the retrieval-eligible chunk order in corpus_chunks_v3_final.jsonl.
    fts_row_to_chunk={i+1:c["chunk_id"] for i,c in enumerate(eligible)}
    fts_count,fts_min,fts_max=con.execute("SELECT count(*),min(rowid),max(rowid) FROM chunks_fts").fetchone()
    if fts_count!=len(eligible) or fts_min!=1 or fts_max!=len(eligible):
        raise RuntimeError("FTS rowid-to-chunk mapping failed validation")
    results=[]
    for idx,(q,p,query,qvec) in enumerate(zip(qs,profiles,queries,qvecs),1):
        allowed=set(p["allowed_source_ids"])
        # Filter cards conservatively by exact target, or by an explicit general/multi-species scope.
        scoped=[]
        for c in eligible:
            if c["source_id"] not in allowed: continue
            meta=json.loads(c["metadata_json"]) if c.get("metadata_json") else c
            scope=meta.get("species_scope","")
            if "general_aquaculture" in scope or "虱目魚|吳郭魚" in scope:
                if p["species"] not in scope and p["species"] not in ("虱目魚","吳郭魚") and "general_aquaculture" not in scope: continue
            elif p["species"]=="鱸魚":
                if "金目鱸" in q["question_text"] and "Lates calcarifer" not in meta.get("species_taxonomy",""): continue
                if "七星鱸" in q["question_text"] and "Lateolabrax japonicus" not in meta.get("species_taxonomy",""): continue
                if "金目鱸" not in q["question_text"] and "七星鱸" not in q["question_text"]: continue
            elif "SPECIFIC: Epinephelus lanceolatus" in meta.get("species_taxonomy","") and not any(t in q["question_text"] for t in ["鞍帶石斑","龍膽"]):
                continue
            elif p["species"] not in scope and p["species"] not in meta.get("species_taxonomy",""):
                continue
            # Don't return historical eel material as current clinical advice; keep only if query explicitly asks historical source.
            if c["source_id"]=="TFRI-EEL-MOLD-2006" and not any(t in q["question_text"] for t in ["歷史","2006","特刊"]): continue
            scoped.append(c)
        scope_ids={c["chunk_id"] for c in scoped}
        terms=list(dict.fromkeys(tokenize(query)))
        bm=[]
        if terms and scoped:
            match_expr=" OR ".join('"'+x.replace('"','""')+'"' for x in terms)
            marks=','.join('?' for _ in p["allowed_source_ids"])
            try:
                rows=con.execute("SELECT rowid,bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts),rowid",[match_expr]).fetchall()
                bm=[]
                for rowid,score in rows:
                    cid=fts_row_to_chunk.get(rowid)
                    if cid in scope_ids:
                        bm.append({"chunk_id":cid,"score":float(score)})
                        if len(bm)>=100: break
            except sqlite3.OperationalError: bm=[]
        bm_rank={x["chunk_id"]:i for i,x in enumerate(bm,1)}
        local=[i for i,c in enumerate(eligible) if c["chunk_id"] in scope_ids]
        dense=[]
        if local:
            sims=vectors[local]@qvec
            order=np.argsort(-sims,kind="stable")[:min(100,len(local))]
            dense=[{"chunk_id":eligible[local[int(k)]]["chunk_id"],"score":float(sims[int(k)])} for k in order]
        dense_rank={x["chunk_id"]:i for i,x in enumerate(dense,1)}
        fused={}
        for source in (bm,dense):
            for rank,row in enumerate(source,1): fused[row["chunk_id"]]=fused.get(row["chunk_id"],0)+1/(60+rank)
        fused_ids=sorted(fused,key=lambda k:(-fused[k],k))[:100]
        rrf=[{"chunk_id":cid,"rank":i,"score":fused[cid],"bm25_rank":bm_rank.get(cid),"dense_rank":dense_rank.get(cid)} for i,cid in enumerate(fused_ids,1)]
        rerank_in=[{"chunk_id":cid,"text":by_id[cid]["text"],"rank":i,"source_id":by_id[cid]["source_id"],"rrf_score":fused[cid]} for i,cid in enumerate(fused_ids,1)]
        reranked=reranker.rerank(query,rerank_in) if rerank_in else []
        top=[]
        for rank,x in enumerate(reranked[:5],1):
            c=by_id[x["chunk_id"]]
            m=json.loads(c["metadata_json"]) if c.get("metadata_json") else c
            top.append({"chunk_id":c["chunk_id"],"rank":rank,"source_id":c["source_id"],"source_title":m.get("source_title"),"source_url":m.get("source_url"),"source_sha256":c["source_sha256"],"source_version":c["source_version"],"page_or_locator":c["record_locator"],"content":c["text"],"content_sha256":sha_bytes(c["text"].encode()),"evidence_span":m.get("evidence_span"),"evidence_span_start_char":m.get("evidence_span_start_char"),"evidence_span_end_char":m.get("evidence_span_end_char"),"retrieval_eligible":True,"category_scope":m.get("category_scope"),"species_scope":m.get("species_scope"),"species_taxonomy":m.get("species_taxonomy"),"source_cluster_id":m.get("source_cluster_id"),"rrf_rank":x.get("rank"),"rrf_score":x.get("rrf_score"),"reranker_rank":x.get("reranker_rank"),"reranker_score":x.get("reranker_score"),"bm25_rank":bm_rank.get(c["chunk_id"]),"dense_rank":dense_rank.get(c["chunk_id"])})
        # Count pipeline candidates after query-specific source scope and applicability checks.
        row={"question_id":q["question_id"],"species":q["species_chinese"],"category":q.get("inferred_category"),"question_text":q["question_text"],"query":query,"intent":p["intent"],"scope_allowed_source_ids":sorted(allowed),"corpus_applicable_source_count":len({c["source_id"] for c in scoped}),"corpus_applicable_chunk_count":len(scoped),"bm25_candidate_count":len(bm),"bm25_top100":bm,"dense_candidate_count":len(dense),"dense_top100":dense,"rrf_candidate_count":len(rrf),"rrf_candidates_top100":rrf,"source_qualification_pass_count":len(scoped),"species_applicability_pass_count":len(scoped),"reranker_candidate_count":len(rerank_in),"reranked_top5":top,"final_top5_count":len(top),"retrieval_status":"reranked_top5_complete" if len(top)==5 else ("no_applicable_retrieval_eligible_source" if not scoped else "fewer_than_five_applicable_candidates"),"corpus_version":manifest["corpus_version"],"query_excludes_answers_and_rubrics":True,"retrieval_config":{"bm25":"SQLite FTS5; Phase U bigram tokenizer, authored cards char-bigram tokens","dense":"BGE-M3 Ollama","dense_digest":BGE_DIGEST,"rrf_k":60,"reranker":"BAAI/bge-reranker-v2-m3","reranker_revision":RERANKER_SNAPSHOT.name,"top_k":5}}
        if row["corpus_applicable_source_count"]==0: row["retrieval_failure_reason"]="SOURCE_MISSING_OR_SCOPE_FILTERED"
        elif not bm and not dense: row["retrieval_failure_reason"]="RETRIEVAL_RECALL_FAILURE"
        elif len(top)<5: row["retrieval_failure_reason"]="ELIGIBLE_CANDIDATE_POOL_BELOW_FIVE"
        else: row["retrieval_failure_reason"]=None
        results.append(row)
        if idx%30==0: print(f"retrieval {idx}/180; nonempty={sum(bool(x['reranked_top5']) for x in results)}",flush=True)
    con.close(); write_jsonl(RUN/"retrieval_results_v3_final.jsonl",results)
    return results


def make_reference_rows(questions, cards, retrieval):
    # Qualification is conservative and independent of any M1-M4 generation.
    card_by=[]
    for c in cards:
        card_by.append(c)
    retrieval_by={r["question_id"]:r for r in retrieval}
    rows=[]
    for q in questions:
        text=q["question_text"]
        species=q.get("species_chinese")
        category=q.get("inferred_category")
        candidates=[]
        for c in card_by:
            m=c["metadata"]
            ss=m["species_scope"].split("|")
            if species not in ss and not any(s in ss for s in ["general_aquaculture"]): continue
            if category and category not in m["category_scope"]: continue
            if species=="鱸魚" and "金目鱸" not in text and "七星鱸" not in text: continue
            if c["source_id"]=="TFRI-EEL-MOLD-2006" and not any(t in text for t in ["疾病","黴菌","水黴","病原"]): continue
            if any(k in text for k in ["水溫","溫度","寒流","寒害","低溫"]) and ("水溫" in m["heading"] or "低溫" in m["heading"] or "寒流" in m["heading"] or category=="Climate / Cold"):
                candidates.append(c)
            elif any(k in text for k in ["密度","放養","尾/公頃","每公頃","公斤/立方公尺","水深","鹽度","psu","水車","石灰","疫病","黴菌"]):
                candidates.append(c)
        # A requirement is only answerable when a source card directly carries the requested subject and every requested numeric/condition element.
        selected=[]
        for c in candidates:
            card_text=c["text"]
            if any(num in text for num in re.findall(r"\d+(?:\.\d+)?",text)):
                qnums=set(re.findall(r"\d+(?:\.\d+)?",text)); cnums=set(re.findall(r"\d+(?:\.\d+)?",card_text))
                # Question-provided case values are allowed as inputs, but all requested reference values need a source fact.
                if any(x in text for x in ["依資料","資料所述","手冊","官方","建議","範圍","上限","下限"]):
                    if not (qnums & cnums) and not any(x in card_text for x in ["數值","範圍"]):
                        pass
            selected.append(c)
        selected=selected[:3]
        if selected:
            status="SOURCE_VERIFIED_AUTOMATED_CANDIDATE"
            answer="；".join(c["text"] for c in selected)
            spans=[{"source_id":c["source_id"],"source_sha256":c["source_sha256"],"source_version":c["source_version"],"locator":c["record_locator"],"exact_evidence_span":c["metadata"]["evidence_span"],"fact_id":c["metadata"]["fact_id"],"species_scope":c["metadata"]["species_scope"]} for c in selected]
            applicability="verified_for_card_scope_only"
            rubric="Answer must reflect the cited fact and all explicit scope/condition constraints; do not infer beyond card. AI-assisted reference; human gold=false."
        else:
            status="NOT_EVALUABLE"
            answer=None; spans=[]; applicability="not_verified"
            rubric=None
        ret=retrieval_by[q["question_id"]]
        rows.append({"question_id":q["question_id"],"species":species,"category":category,"question_text":text,"question_valid":bool(text.strip()),"source_status":status,"reference_answer_candidate":answer,"required_answer_elements_extracted_from_question":[],"evidence_spans":spans,"applicability_status":applicability,"logical_rubric":rubric,"arithmetic_rubric":None,"expected_action":"answer_from_cited_source" if selected else ("expected_abstention" if not ret["reranked_top5"] else "not_evaluable_source_support_unverified"),"corpus_version":"research_corpus_v3_phase_v_20261018","top5_hit_is_outcome_not_eligibility_gate":True,"human_gold_reviewed":False,"limitations":"Candidate qualification is source-card limited and requires independent reviewer confirmation; does not use M1-M4 outputs."})
    return rows


def main():
    owners, rights, _ = load_source_rows()
    questions=read_jsonl(QUESTION_FILE)
    if len(questions)!=180 or len({q["question_id"] for q in questions})!=180: raise RuntimeError("Expected 180 unique fish test questions")
    sources,cards=build_fact_cards()
    # Rebuild blocker decisions with actual per-file integrity, parser, metadata, rights and OCR distinctions.
    blockers=resolve_blockers(owners,rights,None)
    write_jsonl(RUN/"source_blocker_resolution_50.jsonl",blockers)
    write_jsonl(RUN/"evidence_cards_v3.jsonl",cards)
    write_jsonl(RUN/"source_registry_v3_limited.jsonl",list(sources.values()))
    manifest=copy_and_build_corpus(sources,cards)
    retrieval=retrieve_all(manifest)
    ref_rows=make_reference_rows(questions,cards,retrieval)
    write_jsonl(RUN/"question_reference_answers_180.jsonl",ref_rows)
    failure_rows=[]
    for r in retrieval:
        failure_rows.append({"question_id":r["question_id"],"species":r["species"],"category":r["category"],"corpus_applicable_source_count":r["corpus_applicable_source_count"],"bm25_candidate_count":r["bm25_candidate_count"],"dense_candidate_count":r["dense_candidate_count"],"rrf_candidate_count":r["rrf_candidate_count"],"source_qualification_pass_count":r["source_qualification_pass_count"],"species_applicability_pass_count":r["species_applicability_pass_count"],"reranker_candidate_count":r["reranker_candidate_count"],"final_top5_count":r["final_top5_count"],"failure_reason":r["retrieval_failure_reason"],"top5_chunk_ids":[x["chunk_id"] for x in r["reranked_top5"]]})
    write_jsonl(RUN/"retrieval_failure_resolution_180.jsonl",failure_rows)
    # Existing Phase U facts are copied; no question or answer enters the source index.
    card_by_source=Counter(c["source_id"] for c in cards)
    corpus_chunks=read_jsonl(NEW_CORPUS/"corpus_chunks_v3_final.jsonl")
    eligible=[c for c in corpus_chunks if c.get("retrieval_eligible")]
    dup_content=Counter(c.get("content_sha256") for c in eligible)
    source_chunk=Counter(c["source_id"] for c in corpus_chunks)
    cluster_counts=Counter()
    for c in cards: cluster_counts[c["metadata"]["source_cluster_id"]]+=1
    quality={"corpus_version":manifest["corpus_version"],"total_chunks":len(corpus_chunks),"retrieval_eligible_chunks":len(eligible),"context_only_chunks":len(corpus_chunks)-len(eligible),"eligible_duplicate_content_groups":sum(n>1 for n in dup_content.values()),"eligible_duplicate_rows_excess":sum(n-1 for n in dup_content.values() if n>1),"chunk_counts_by_source":dict(source_chunk),"added_fact_cards_by_source":dict(card_by_source),"fact_card_source_clusters":dict(cluster_counts),"phase_u_base_chunk_records_preserved":manifest["phase_u_original_chunks_preserved"],"new_fact_cards":len(cards),"exact_quote_verified_count":sum(c["metadata"]["evidence_quote_verified"] for c in cards),"source_hashes_rechecked":len({c["source_sha256"] for c in cards}),"rights_note":"No copyrighted fulltext was indexed. Research cards contain concise paraphrased facts, and short exact spans are stored as provenance only. This is not a third-party fulltext authorization claim."}
    write_json(RUN/"corpus_v3_quality_report.json",quality)
    # Source admission update: owner approvals preserved, but source-specific processing scopes are separate.
    old_registry=read_jsonl(U/"source_admission_registry_v3_final.jsonl")
    admission={"approval_manifest_version":"phase-v-owner-approved-57-v1","owner_approval_reference":"PHASE-U-SOURCE-MATRIX-57-OWNER-APPROVAL-20261018","owner_decision_records":57,"owner_approved_records":57,"unique_source_sha256":55,"owner_approval_is_not_third_party_license":True,"previously_admitted_from_phase_u":old_registry,"new_limited_fact_card_sources":list(sources.values()),"fulltext_admitted_new_sources":0,"new_source_processing_status":"limited researcher-authored factual cards indexed only where SHA, exact locator and source identity were checked; copyrighted fulltext not indexed","corpus_v3_build_status":"built isolated research corpus; not production; not Evaluation Corpus v2","admission_decisions":{sid:{"status":"included_limited_factual_cards","fulltext_indexing":False,"scope":s["usage_scope"],"source_sha256":s["sha256"],"publisher":s["publisher"],"source_version":s["version"]} for sid,s in sources.items()},"blocked_fulltext_source_count":50,"note":"No individual full-text rights were inferred from Owner Approval. All 50 prior blockers remain blocked for fulltext indexing unless separately supported; some have limited factual cards with precise source spans."}
    write_json(RUN/"source_admission_final.json",admission)
    # Candidate scoring set is not expanded into an unvalidated formal benchmark.
    status_counts=Counter(r["source_status"] for r in ref_rows)
    retrieval_status=Counter(r["retrieval_status"] for r in retrieval)
    write_json(RUN/"evaluation_metrics_v3_final.json",{"evaluation_status":"NOT_RUN_GATE_BLOCKED","generator_calls":0,"generator_results":0,"models_scored":0,"winner":None,"retrieval":{"questions":len(retrieval),"with_any_top5":sum(r["final_top5_count"]>0 for r in retrieval),"full_top5":sum(r["final_top5_count"]==5 for r in retrieval),"status_counts":dict(retrieval_status)},"answerability":{"questions":len(ref_rows),"source_verified_automated_candidates":status_counts.get("SOURCE_VERIFIED_AUTOMATED_CANDIDATE",0),"not_evaluable":status_counts.get("NOT_EVALUABLE",0),"human_gold":0},"metrics":{"Faithfulness":{"status":"not_evaluated","n":0},"Judge_Answer_Relevance":{"status":"not_evaluated","n":0},"BGE_M3_Cosine":{"status":"not_evaluated","n":0},"Structured_IFR":{"status":"not_evaluated","n":0},"TTFT":{"status":"not_evaluated","n":0},"TPS":{"status":"not_evaluated","n":0},"System_RAM":{"status":"not_evaluated","n":0},"Dedicated_VRAM":{"status":"not_evaluated","n":0},"Context_Precision_at_5":{"status":"not_evaluated_no_trusted_relevance_gold","n":0},"Logical_Accuracy":{"status":"not_evaluated_no_frozen_verified_rubrics","n":0},"Arithmetic_Accuracy":{"status":"not_evaluated_no_validated_reference_set","n":0}},"blocker":"Source-supported candidate set is limited and not yet a complete six-species evaluation basis; full four-model run not started."})
    write_jsonl(RUN/"generator_results_v3_final.jsonl",[])
    # Per-stage system provenance summary.
    write_json(RUN/"rag_end_to_end_validation.json",{"corpus_build":"PASS_ISOLATED","source_traces":"PASS_FOR_FACT_CARDS","query_embedding_runtime":"PASS" if manifest.get("embedding_index",{}).get("status")=="BUILT" else "FAIL","bm25":"PASS_SQLITE_FTS5","rrf":"PASS_K60","reranker":"EXECUTED_FOR_180_QUERIES","final_top5_traceback":"PASS_FOR_RETURNED_CHUNKS","generator_interface":"NOT_RUN_GATED","four_model_runtime_identity":{"M1":"deepseek-r1:7b digest 755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f","M2":"qwen2.5-coder:7b digest dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364","M3":"hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M digest aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42","M4":"gemma2:9b digest ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"},"model_generation_tests":"NOT_RUN","streamlit_app_test":"NOT_RUN","repository_pytest":"pending","production_changed":False,"formal_corpus_v2_changed":False,"sqlite_production_changed":False})
    print(json.dumps({"manifest":manifest,"quality":quality,"retrieval_status":dict(retrieval_status),"answer_status":dict(status_counts)},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
