from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\my project\115_marine_project")
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3e_auto_source_crawl"
STAGE = ROOT / "my_data/_official_source_staging/phase20_1E_step3E"
DL = Path(r"C:\Users\ethan\Downloads")
BASE = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3"
SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def write_json(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_jsonl(name, rows):
    (OUT / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")

def find_exact_existing(path_name: str, digest: str):
    for p in (ROOT / "my_data").rglob(path_name):
        if p.is_file() and STAGE not in p.parents and sha(p) == digest:
            return p
    return None

OUT.mkdir(parents=True, exist_ok=True)
for d in [STAGE / "raw/pdf", STAGE / "raw/html", STAGE / "metadata", STAGE / "quarantine", STAGE / "crawl_logs"]:
    d.mkdir(parents=True, exist_ok=True)

page_visits = [
    ("MOA-LAW-ATTACHMENTS", "動物用藥品使用準則－法規附件來源頁", "https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443", "MOA", "Current page rendered; Attachment I link visible; annex bytes were blocked by browser client."),
    ("MOA-LAW-CURRENT", "動物用藥品使用準則", "https://law.moa.gov.tw/LawContent.aspx?id=FL035443", "MOA", "Current consolidated Article 3 refers aquaculture drug items, species, use, method, quantity and withdrawal rules to Annex I."),
    ("FA-HAZARD", "陸上魚塭養殖寒害潛勢分析", "https://www.fa.gov.tw/view.php?id=383&theme=web_structure", "FA", "Official page text names milkfish, tilapia, seabass and grouper; browser-view only."),
    ("FA-SEA-CAGE", "海洋箱網養殖寒害潛勢分析", "https://www.fa.gov.tw/view.php?id=384&theme=web_structure", "FA", "Official page text covers seabass/grouper sea-cage cold risk; browser-view only."),
    ("FA-COLD", "養殖漁業防寒須知", "https://www.fa.gov.tw/view.php?id=385&theme=web_structure", "FA", "Official page text includes tropical fish cold protection; browser-view only."),
    ("TFRIN-MANUAL17", "漁電共生養殖技術應用手冊（下）（技術手冊17）", "https://www.tfrin.gov.tw/ws.php?id=246", "TFRIN", "Official publication metadata and seven attachment links; page states publication 2023-08-31 and modified 2025-12-09."),
    ("TFRIN-MILKFISH-COLD", "寒流侵襲時造成虱目魚死亡的原因為何？", "https://www.tfrin.gov.tw/theme_data.php?id=426&theme=knowledge_explanation", "TFRIN", "Question text links cold-front temperatures, milkfish tropical sensitivity, overwintering measures and red-spot-disease bacteria; browser-view only."),
    ("TFRIN-GROUPER-DISEASE", "石斑魚養殖疾病防疫", "https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology", "TFRIN", "Official article page links an attached 10-page PDF; page date 2017-12-01, modified 2021-07-13."),
    ("TFRIN-FCR-EXPLAIN", "何謂飼料換肉率？", "https://www.tfrin.gov.tw/theme_data.php?id=385&theme=knowledge_explanation", "TFRIN", "Official text defines feed weight divided by weight gain; lacks deterministic input assumptions/tolerance."),
    ("TFRIN-TILAPIA-ARTICLE", "吳郭魚雜交與自交系的成長比較－快速成長品系之研發", "https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data", "TFRIN", "Official catalog gives publication 2008-12-31, journal 16(2), pages 41-47 and attached PDF."),
    ("TFRIN-EEL-QA", "請問從海裡抓到的鱸鰻鰻線如何養殖？", "https://www.tfrin.gov.tw/theme_data.php?id=485&sub_theme=fishery&theme=qa", "TFRIN", "Official page is specifically about 鱸鰻 and compares eel taxa; dated 2012-02-21; browser-view only."),
    ("TFRIN-EEL-FRY", "白鰻（日本鰻）魚苗空運注意事項", "https://www.tfrin.gov.tw/theme_data.php?id=496&sub_theme=fishery&theme=qa", "TFRIN", "Official page is explicitly Japanese eel fry transport; dated 2012-04-18 and warns data do not apply to other eel species."),
]
page_rows = [{"source_id": sid, "title": title, "url": url, "publisher_domain": host, "visited": True, "capture_type": "browser_view_only", "raw_html_saved": False, "local_file": None, "observation": note} for sid, title, url, host, note in page_visits]
(STAGE / "crawl_logs/browser_page_observations.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in page_rows), encoding="utf-8")

downloads = [
    {"source_id":"TFRIN-MANUAL17", "title":"技術手冊17-漁電共生養殖技術應用手冊（下）", "landing":"https://www.tfrin.gov.tw/ws.php?id=246", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=89&file_name=kAQdNmcnqosGHKer4iYetlbWGPlusEz9bE916GhpAWGEqualWGEqualOeAfIF3oPfMRMgEpFOWGPlusTvaapnepKVGqSF9eYj6lZFWe5lEGzwQ", "filename":"技術手冊17-漁電共生養殖技術應用手冊(下).pdf", "download_path":DL/"技術手冊17-漁電共生養殖技術應用手冊(下).pdf", "published":"2023-08-31", "revised":"2025-12-09", "species":SPECIES, "topics":["aquaculture management"], "rights":"TFRI page indicates reproduction/digitization/reprint permission is required; permission unresolved."},
    {"source_id":"TFRIN-MANUAL17", "title":"技術手冊17 第三章第二節 金目鱸", "landing":"https://www.tfrin.gov.tw/ws.php?id=246", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=91&file_name=AmBy1bWviljJtutFM67rWGSlashSkT6B0LNQa70L5O2o6Sz3LXimNnQgWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQw93DPw4bb3", "filename":"技術手冊17-第三章水產養殖管理技術 第二節金目鱸.pdf", "download_path":DL/"技術手冊17-第三章水產養殖管理技術 第二節金目鱸.pdf", "published":"2023-08-31", "revised":"2025-12-09", "species":["鱸魚"], "topics":["Fact","Water Quality","Climate / Cold"], "rights":"TFRI page indicates reproduction/digitization/reprint permission is required; permission unresolved."},
    {"source_id":"TFRIN-MANUAL17", "title":"技術手冊17 第三章第三節 七星鱸", "landing":"https://www.tfrin.gov.tw/ws.php?id=246", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=92&file_name=bb3AmBy1bW43ilqEeAKyWW5DNnzJfL9NQa70L5O2o6Sz3LXimNnQgWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQw93DPw4", "filename":"技術手冊17-第三章水產養殖管理技術 第三節七星鱸.pdf", "download_path":DL/"技術手冊17-第三章水產養殖管理技術 第三節七星鱸.pdf", "published":"2023-08-31", "revised":"2025-12-09", "species":["鱸魚"], "topics":["Fact","Water Quality","Climate / Cold"], "rights":"TFRI page indicates reproduction/digitization/reprint permission is required; permission unresolved."},
    {"source_id":"TFRIN-MANUAL17", "title":"技術手冊17 第三章第四節 石斑魚", "landing":"https://www.tfrin.gov.tw/ws.php?id=246", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=93&file_name=bWoeuBGVyQDPWGPlus5EBZhEovPmwm2r4dWGPlusJTjWGPluseUjyJIq6O5sWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQw93DPw4bb3AmBy1", "filename":"技術手冊17-第三章水產養殖管理技術 第四節石斑魚.pdf", "download_path":DL/"技術手冊17-第三章水產養殖管理技術 第四節石斑魚.pdf", "published":"2023-08-31", "revised":"2025-12-09", "species":["石斑魚"], "topics":["Fact","Water Quality","Climate / Cold"], "rights":"TFRI page indicates reproduction/digitization/reprint permission is required; permission unresolved."},
    {"source_id":"TFRIN-MANUAL17", "title":"技術手冊17 第三章第六節 烏魚", "landing":"https://www.tfrin.gov.tw/ws.php?id=246", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=95&file_name=w93DPw4bb3AmBy1bW7NPhLgJwguLvwdvU9ObQuAWGEqualWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQ", "filename":"技術手冊17-第三章水產養殖管理技術 第六節烏魚.pdf", "download_path":DL/"技術手冊17-第三章水產養殖管理技術 第六節烏魚.pdf", "published":"2023-08-31", "revised":"2025-12-09", "species":["烏魚"], "topics":["Fact","Water Quality","Climate / Cold"], "rights":"TFRI page indicates reproduction/digitization/reprint permission is required; permission unresolved."},
    {"source_id":"TFRIN-GROUPER-DISEASE", "title":"07 石斑魚養殖疾病防疫", "landing":"https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=13403&file_name=p6cgLKOWGSlashVewT7C0WGEqualMIo9LkDry6IF75E34MMJUXa7xkKk", "filename":"07石斑魚養殖疾病防疫.pdf", "download_path":STAGE/"raw/pdf/07石斑魚養殖疾病防疫.pdf", "published":"2017-12-01", "revised":"2021-07-13", "species":["石斑魚"], "topics":["Disease"], "rights":"unknown; resolve reuse terms before admission."},
    {"source_id":"TFRIN-TILAPIA-ARTICLE", "title":"吳郭魚雜交與自交系的成長比較－快速成長品系之研發", "landing":"https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data", "direct":"https://www.tfrin.gov.tw/redirect_files.php?id=9371&file_name=2Zib4jMWLRB0ClavAEI9MML7lcDrVs8JiByD2vvxwrg1IzVld5WGPlusvOTDoeh3ueWGSlashaKBiaIEAehj224A3vAAT7C1LJ0ZQxp3aJI1SygWGPlustEpu5labFLLlWFgmpPmWGPlus777OY2Z", "filename":"水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf.pdf", "download_path":DL/"水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf.pdf", "published":"2008-12-31", "revised":None, "species":["吳郭魚"], "topics":["Fact"], "rights":"unknown; study results limited to named strains and stated 364-day culture conditions."},
]

try:
    import fitz
except Exception as e:
    fitz = None
    fitz_error = repr(e)
else:
    fitz_error = None

download_rows, integrity_rows, duplicate_rows = [], [], []
for d in downloads:
    p = d["download_path"]
    if not p.is_file():
        download_rows.append({"source_id":d["source_id"],"title":d["title"],"direct_download_url":d["direct"],"attempt_status":"download_not_present_locally","download_path":str(p)})
        continue
    digest, size = sha(p), p.stat().st_size
    sig = p.open("rb").read(5)
    page_count, text_chars, pdf_open, error = None, None, False, None
    if fitz:
        try:
            doc = fitz.open(p)
            page_count = len(doc)
            text_chars = [len(pg.get_text()) for pg in doc]
            pdf_open = page_count > 0
            doc.close()
        except Exception as e:
            error = repr(e)
    existing = None if p.is_relative_to(STAGE) else find_exact_existing(d["filename"], digest)
    staged = p.is_relative_to(STAGE)
    row = {
        "source_id":d["source_id"],"title":d["title"],"publisher":"農業部水產試驗所",
        "official_landing_url":d["landing"],"direct_download_url":d["direct"],"final_url":"unknown; browser download API returned local file path but did not expose redirect target",
        "file_type":"PDF","download_method":"Codex In-app Browser native downloadMedia on official page link",
        "browser_download_path":str(p) if not staged else None,"local_path":str(p) if staged else (str(existing) if existing else None),
        "staged_path":str(p) if staged else None,"retrieved_at_local":datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(),
        "published_at":d["published"],"revised_at":d["revised"],"effective_at":None,"file_size":size,"sha256":digest,
        "pdf_page_count":page_count,"species_scope":d["species"],"topic_category":d["topics"],
        "copyright_or_usage_terms":d["rights"],"source_identity_status":"official page-to-link relationship observed; file bytes validated",
        "version_status":"page metadata captured; official revision linkage requires review where noted",
        "document_validation_status":"valid_pdf" if sig == b"%PDF-" and pdf_open else "validation_failed",
        "admission_status":"not_admitted","duplicate_reference_only":bool(existing),"duplicate_of":str(existing) if existing else None,
    }
    download_rows.append({**row,"attempt_status":"downloaded_duplicate_reference" if existing else "downloaded_and_staged"})
    integrity_rows.append({"source_id":d["source_id"],"file":d["filename"],"path":str(p),"size_bytes":size,"sha256":digest,"pdf_signature":"%PDF-" if sig == b"%PDF-" else sig.hex(),"pdf_opened":pdf_open,"page_count":page_count,"extractable_text_chars_per_page":text_chars,"valid":sig == b"%PDF-" and pdf_open and size > 0,"error":error})
    if existing:
        duplicate_rows.append({"sha256":digest,"source_id":d["source_id"],"downloaded_copy":str(p),"canonical_existing_file":str(existing),"stored_duplicate":False})
    # Hash-based names remain unique even when several Chinese filenames normalize identically.
    safe = f"{d['source_id']}_{digest[:16]}"
    (STAGE / "metadata" / f"{safe}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

write_jsonl("downloaded_source_manifest.jsonl", download_rows)
write_json("file_integrity_validation.json", {"checked_at_utc":now(),"validator":"PDF signature + PyMuPDF open/page extraction","pymupdf_available":fitz is not None,"pymupdf_error":fitz_error,"downloaded_pdf_count":len(integrity_rows),"valid_pdf_count":sum(x["valid"] for x in integrity_rows),"new_unique_staged_files":sum(bool(x.get("staged_path")) for x in download_rows),"duplicate_reference_count":len(duplicate_rows),"pdf_pages_total":sum(x["page_count"] or 0 for x in integrity_rows),"files":integrity_rows})
write_json("source_duplicate_registry.json", {"duplicate_count":len(duplicate_rows),"duplicates":duplicate_rows,"rule":"Identical SHA-256 bytes are referenced by path only; no duplicate copy was stored in staging."})

law_annex_url="https://law.moa.gov.tw/Download.ashx?FileID=13570&id=FL035443&type=LAW"
manual_links=[
    ("技術手冊17-漁電共生養殖技術應用手冊(下).pdf","https://www.tfrin.gov.tw/redirect_files.php?id=89&file_name=kAQdNmcnqosGHKer4iYetlbWGPlusEz9bE916GhpAWGEqualWGEqualOeAfIF3oPfMRMgEpFOWGPlusTvaapnepKVGqSF9eYj6lZFWe5lEGzwQ"),
    ("技術手冊17-第三章水產養殖管理技術 第一節白蝦.pdf","https://www.tfrin.gov.tw/redirect_files.php?id=90&file_name=w93DPw4bb3AmBy1bWrTjx6M4je88hIRZbpfZVlgWGEqualWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQ"),
    ("技術手冊17-第三章水產養殖管理技術 第二節金目鱸.pdf",downloads[1]["direct"]),
    ("技術手冊17-第三章水產養殖管理技術 第三節七星鱸.pdf",downloads[2]["direct"]),
    ("技術手冊17-第三章水產養殖管理技術 第四節石斑魚.pdf",downloads[3]["direct"]),
    ("技術手冊17-第三章水產養殖管理技術 第五節午仔魚.pdf","https://www.tfrin.gov.tw/redirect_files.php?id=94&file_name=FB3U7AtQR1ZvKoJWGPlusAWGPlus8EaQm2r4dWGPlusJTjWGPluseUjyJIq6O5sWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQw93DPw4bb3AmBy1bW"),
    ("技術手冊17-第三章水產養殖管理技術 第六節烏魚.pdf",downloads[4]["direct"]),
]
attachment_links=[{"link_type":"official_pdf_attachment","title":"附件一 水產動物用藥品使用規範修正規定.pdf","url":law_annex_url,"landing_url":"https://law.moa.gov.tw/LawContentSource.aspx?id=FL035443","in_scope":True},
                  *[{"link_type":"official_pdf_attachment","title":n,"url":u,"landing_url":"https://www.tfrin.gov.tw/ws.php?id=246","in_scope":("白蝦" not in n and "午仔魚" not in n)} for n,u in manual_links],
                  {"link_type":"official_pdf_attachment","title":"07石斑魚養殖疾病防疫.pdf","url":downloads[5]["direct"],"landing_url":downloads[5]["landing"],"in_scope":True},
                  {"link_type":"official_pdf_attachment","title":"水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf","url":downloads[6]["direct"],"landing_url":downloads[6]["landing"],"in_scope":True}]
page_link_rows=[{"link_type":"official_landing_page","source_id":sid,"title":title,"url":url,"visited":True} for sid,title,url,_,_ in page_visits]
write_jsonl("official_discovered_links.jsonl", page_link_rows + attachment_links)

attempts=[]
for r in download_rows:
    attempts.append({"source_id":r["source_id"],"url":r["direct_download_url"],"method":"browser_downloadMedia","outcome":r["attempt_status"],"path":r.get("browser_download_path") or r.get("staged_path"),"sha256":r.get("sha256"),"error":None})
attempts += [
    {"source_id":"MOA-LAW-FL035443","url":law_annex_url,"method":"Codex in-app browser attachment navigation/click","outcome":"failed","path":None,"sha256":None,"error":"net::ERR_BLOCKED_BY_CLIENT; no raw PDF bytes returned."},
    {"source_id":"MOA-LAW-FL035443","url":law_annex_url,"method":"approved web retrieval connector","outcome":"failed","path":None,"sha256":None,"error":"400 Unsupported content-type: application/octet-stream; binary body not exposed."},
]
write_jsonl("download_attempts.jsonl", attempts)
write_jsonl("blocked_downloads.jsonl", [x for x in attempts if x["outcome"] == "failed"])
with (STAGE / "crawl_logs/download_attempts.jsonl").open("w",encoding="utf-8") as f:
    f.writelines(json.dumps(x,ensure_ascii=False)+"\n" for x in attempts)

official_sources = [
    {"source_id":"MOA-LAW-FL035443","title":"動物用藥品使用準則－水產動物用藥品使用規範附表","publisher":"農業部","landing":"https://law.moa.gov.tw/LawContent.aspx?id=FL035443","direct":law_annex_url,"published":None,"revised":"2025-01-08 parent consolidated law; Annex I historical revision shown as 2019-04-22","effective":None,"species":SPECIES,"categories":["Safe Medication / Law"],"download":"blocked_browser_and_binary_connector","validation":"browser_view_only","status":"needs_version_review","blocker":"Attachment bytes not available; parent date does not prove Annex I version/current item-specific authorization."},
    {"source_id":"FA-HAZARD","title":"陸上魚塭養殖寒害潛勢分析","publisher":"農業部漁業署","landing":"https://www.fa.gov.tw/view.php?id=383&theme=web_structure","direct":None,"published":None,"revised":"2026-06-19 recorded in prior Phase 20.1 source registry; current page body did not independently expose a file","effective":None,"species":["虱目魚","吳郭魚","石斑魚","鱸魚"],"categories":["Climate / Cold"],"download":"no attachment exposed","validation":"browser_view_only","status":"needs_version_review","blocker":"No local raw HTML/PDF; page has not been snapshotted and applicability spans require review."},
    {"source_id":"FA-SEA-CAGE","title":"海洋箱網養殖寒害潛勢分析","publisher":"農業部漁業署","landing":"https://www.fa.gov.tw/view.php?id=384&theme=web_structure","direct":None,"published":None,"revised":None,"effective":None,"species":["石斑魚","鱸魚"],"categories":["Climate / Cold"],"download":"no attachment exposed","validation":"browser_view_only","status":"needs_provenance_review","blocker":"Browser-rendered page only; no raw HTML or revisioned downloadable file saved."},
    {"source_id":"FA-COLD","title":"養殖漁業防寒須知","publisher":"農業部漁業署","landing":"https://www.fa.gov.tw/view.php?id=385&theme=web_structure","direct":None,"published":None,"revised":"unknown in current visible content; prior registry recorded 2026-05-30","effective":None,"species":["虱目魚","吳郭魚"],"categories":["Climate / Cold"],"download":"no attachment exposed","validation":"browser_view_only","status":"needs_version_review","blocker":"No local raw HTML/PDF; date-to-current-content linkage and exact version not frozen."},
    {"source_id":"TFRIN-MILKFISH-COLD","title":"寒流侵襲時造成虱目魚死亡的原因為何？","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=426&theme=knowledge_explanation","direct":None,"published":None,"revised":"2026-10-09 page footer date observed","effective":None,"species":["虱目魚"],"categories":["Disease","Climate / Cold"],"download":"HTML page visible only","validation":"browser_view_only","status":"needs_provenance_review","blocker":"No raw HTML saved; statement is one official Q&A and needs atomic evidence/proposition review."},
    {"source_id":"TFRIN-GROUPER-DISEASE","title":"石斑魚養殖疾病防疫","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology","direct":downloads[5]["direct"],"published":"2017-12-01","revised":"2021-07-13","effective":None,"species":["石斑魚"],"categories":["Disease"],"download":"downloaded_and_staged","validation":"valid_pdf_10_pages_sha256_verified","status":"ready_for_admission_review","blocker":"Reuse terms unknown; proposition-level evidence and disease-currentness review remain for admission."},
    {"source_id":"TFRIN-MANUAL17","title":"漁電共生養殖技術應用手冊（下）","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/ws.php?id=246","direct":None,"published":"2023-08-31","revised":"2025-12-09 web page modification","effective":None,"species":["石斑魚","鱸魚","烏魚"],"categories":["Fact","Water Quality","Climate / Cold"],"download":"five target-relevant PDFs downloaded; all exact SHA duplicates of existing my_data files","validation":"valid_pdf_and_official_page_link_verified","status":"needs_rights_review","blocker":"TFRI page requires permission for reproduction/digitization/reprint; no permission; frozen context_only eligibility unchanged."},
    {"source_id":"TFRIN-TILAPIA-ARTICLE","title":"吳郭魚雜交與自交系的成長比較－快速成長品系之研發","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=1557&sub_theme=special_message_old&theme=book_data","direct":downloads[6]["direct"],"published":"2008-12-31","revised":None,"effective":None,"species":["吳郭魚"],"categories":["Fact"],"download":"browser download hash matches existing local PDF; duplicate reference only","validation":"valid_pdf_7_pages_sha256_matched_catalog_attachment","status":"ready_for_admission_review","blocker":"Research result only applies to study strains and stated culture conditions; not cold-hardiness evidence; usage rights review pending."},
    {"source_id":"TFRIN-SGR-FCR","title":"銀紋笛鯛魚苗生長／飼料效率研究公式來源","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/redirect_files.php?file_name=aBXgWGEqualWGEqual3MNrCMfywOINoS8mgC&id=9564","direct":None,"published":None,"revised":None,"effective":None,"species":["銀紋笛鯛魚苗（非六個目標魚種）"],"categories":["Calculation"],"download":"not_attempted_out_of_scope","validation":"not_downloaded","status":"rejected","blocker":"Source species and experimental scope do not match six candidate species; no transfer of formula assumptions."},
    {"source_id":"TFRIN-FCR-EXPLAIN","title":"何謂飼料換肉率？","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=385&theme=knowledge_explanation","direct":None,"published":None,"revised":None,"effective":None,"species":SPECIES,"categories":["Calculation"],"download":"HTML page visible only","validation":"browser_view_only","status":"needs_applicability_review","blocker":"Defines feed mass divided by gain only; no complete variable/valid-range/rounding/tolerance framework."},
    {"source_id":"TFRIN-EEL-QA","title":"請問從海裡抓到的鱸鰻鰻線如何養殖？","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=485&sub_theme=fishery&theme=qa","direct":None,"published":"2012-02-21","revised":None,"effective":None,"species":["鱸鰻（taxon-specific; not generic eel）"],"categories":["Fact","Water Quality","Disease","Climate / Cold"],"download":"HTML page visible only","validation":"browser_view_only","status":"needs_applicability_review","blocker":"Taxon-specific and historical; target species mapping (鰻魚) is not resolved; do not generalize to Japanese eel."},
    {"source_id":"TFRIN-EEL-FRY","title":"白鰻（日本鰻）魚苗空運注意事項","publisher":"農業部水產試驗所","landing":"https://www.tfrin.gov.tw/theme_data.php?id=496&sub_theme=fishery&theme=qa","direct":None,"published":"2012-04-18","revised":None,"effective":None,"species":["日本鰻魚苗 only"],"categories":["Fact","Climate / Cold"],"download":"HTML page visible only","validation":"browser_view_only","status":"needs_applicability_review","blocker":"Specifically limits its figures to Japanese eel fry transport, not grow-out or other eel species; historical Q&A."},
]

source_by_id = {x["source_id"]:x for x in official_sources}
write_jsonl("source_admission_review_queue.jsonl", [{**x,"admission_status":"not_admitted"} for x in official_sources])
write_json("source_version_comparison.json", {"checked_at_utc":now(),"items":[
    {"source_id":"MOA-LAW-FL035443","parent_consolidated_revision":"2025-01-08","Annex_I_revision_observed_in_law_history":"2019-04-22","current_attachment_bytes_match":"unknown; browser attachment request blocked and no bytes obtained","conclusion":"Do not infer current Annex I item-specific authorization from parent revision date."},
    {"source_id":"TFRIN-MANUAL17","official_page_publication":"2023-08-31","official_page_modified":"2025-12-09","browser_downloads_match_existing_files_by_sha256":True,"PDF published/revision linkage":"exact file bytes match local copies; page modified date is not itself a PDF revision date","rights":"permission required per page notice; not obtained"},
    {"source_id":"TFRIN-GROUPER-DISEASE","official_page_date":"2017-12-01","official_page_modified":"2021-07-13","downloaded_pdf_page_count":10,"PDF internal creation/modification":"2017 metadata reported by pdfinfo; 10-page document; exact URL attachment matched through official page"},
    {"source_id":"TFRIN-TILAPIA-ARTICLE","official_publication":"2008-12-31","issue":"16(2)","pages":"41-47","catalog_attachment_hash_matches_local_pdf":True,"scope":"named tilapia strains and 364-day culture conditions"},
    {"source_id":"FA-HAZARD/FA-SEA-CAGE/FA-COLD","version":"page content observed in browser; no local raw HTML/PDF; exact content snapshot/version checksum unavailable"},
    {"source_id":"TFRIN-MILKFISH-COLD/TFRIN-FCR-EXPLAIN/TFRIN-EEL-QA/TFRIN-EEL-FRY","version":"browser-view pages; no raw HTML bytes saved; page/footer dates are not a substitute for archived content checksum"}
]})

# Attach candidate-source mappings to the frozen Step 3C matrix; formal ready counts stay unchanged.
matrix_path=BASE/"step3c_evidence_expansion/evidence_matrix_after_step3c.json"
baseline=json.loads(matrix_path.read_text(encoding="utf-8-sig"))
mapping={
    ("虱目魚","Disease"): ["TFRIN-MILKFISH-COLD"], ("虱目魚","Climate / Cold"): ["TFRIN-MILKFISH-COLD","FA-HAZARD","FA-COLD"],
    ("吳郭魚","Fact"): ["TFRIN-TILAPIA-ARTICLE"], ("吳郭魚","Climate / Cold"): ["FA-HAZARD","FA-COLD"],
    ("石斑魚","Disease"): ["TFRIN-GROUPER-DISEASE","TFRIN-MANUAL17"], ("石斑魚","Climate / Cold"): ["FA-HAZARD","FA-SEA-CAGE","TFRIN-MANUAL17"],
    ("鱸魚","Climate / Cold"): ["FA-HAZARD","FA-SEA-CAGE","TFRIN-MANUAL17"], ("烏魚","Disease"): ["TFRIN-MANUAL17"],
    ("鰻魚","Fact"): ["TFRIN-EEL-QA","TFRIN-EEL-FRY"], ("鰻魚","Water Quality"): ["TFRIN-EEL-QA"], ("鰻魚","Disease"): ["TFRIN-EEL-QA"], ("鰻魚","Climate / Cold"): ["TFRIN-EEL-QA","TFRIN-EEL-FRY"],
}
for sp in SPECIES:
    for cat in ["Fact","Water Quality","Disease","Climate / Cold","Safe Medication / Law","Calculation"]:
        if cat == "Safe Medication / Law": mapping[(sp,cat)] = ["MOA-LAW-FL035443"]
        if cat == "Calculation": mapping[(sp,cat)] = ["TFRIN-FCR-EXPLAIN"]
cells=[]
for c in baseline["cells"]:
    ids=mapping.get((c["species"],c["category"]),[])
    cells.append({**c,"official_source_ids_observed":ids,"new_external_staged_candidates":1 if (c["species"],c["category"])==("石斑魚","Disease") else 0,"external_admitted_ready":0,"total_formal_ready":c.get("baseline_ready",0)+c.get("new_existing_corpus_silver_ready",0),"formal_ready_changed":False,"source_review_status":"candidate_staged_not_admitted" if ids else c.get("source_review_status")})
write_json("source_to_species_category_matrix.json", {"checked_at_utc":now(),"baseline_source":"Step 3C frozen 36-cell matrix","target_units_per_cell":5,"official_source_ids_mapped_to_cells":True,"source_presence_is_not_evidence_unit_count":True,"cells":cells})
write_json("remaining_source_gaps.json", {"checked_at_utc":now(),"formal_counts_unchanged":True,"normal_risk":{"ready":11,"target":120,"shortfall":109,"new_candidate_not_admitted":[{"species":"石斑魚","category":"Disease","source_id":"TFRIN-GROUPER-DISEASE","status":"source staged; evidence propositions, rights and corpus admission remain unreviewed"}]},"medication_law":{"verified_ready":0,"target":30,"shortfall":30,"blockers":["Current Annex I raw bytes could not be acquired through browser or web retrieval connector.","Annex I item/version and exact pages/spans cannot be confirmed.","Specific species, medicine, indication and authorized use require item-level review."]},"calculation":{"verified_ready":0,"target":30,"shortfall":30,"blockers":["FCR page is conceptual only.","Silver-croaker fry article is out of target species scope.","No target-species formula with variable definitions, units, valid ranges, assumptions, rounding and tolerance was verified."]},"scope_notes":["Official FA cold pages and TFRI FAQ pages were browser-view only; no raw HTML saved.","Manual 17 and tilapia article bytes matched local files; rights/scope decisions still required.","Eel Q&A pages are old and taxon-specific; no general eel inference."]})

links_total=len(page_link_rows)+len(attachment_links)
write_json("browser_capability_preflight.json", {"checked_at_utc":now(),"available_browser":"Codex In-app Browser via unified-computer-use cua_repl","browser_tab_navigation":"pass","dom_accessibility_read":"pass","official_pdf_native_download":"pass (7 PDFs)","browser_dom_only_pages":"12; no raw HTML saved","dedicated_browser_tool":"no separate browser MCP tool surfaced; CUA browser was callable","local_file_access":"PowerShell verified Downloads and staging paths","sandbox_write":"pass for new workspace staging and report paths","limitations":["MOA Download.ashx blocked by browser net::ERR_BLOCKED_BY_CLIENT.","Browser download operation did not expose final redirect URL for files."]})
proxy={k:os.environ.get(k) for k in ["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY","http_proxy","https_proxy","all_proxy","no_proxy"]}
proxy_sanitized={k:("http://127.0.0.1:9" if v and "127.0.0.1:9" in v else ("[set; redacted]" if v and "@" in v else v)) for k,v in proxy.items()}
write_json("network_route_diagnostics.json", {"checked_at_utc":now(),"shell_proxy_environment":proxy_sanitized,"credentials_recorded":False,"prior_shell_failure":{"stage":"TCP connect to configured loopback proxy, before TLS/HTTP","exception":"ConnectionRefusedError / WinError 10061","source":"Phase 20.1E Step 3B/3C logs"},"this_execution":{"browser_official_pages_connected":True,"browser_downloads_succeeded":7,"local_proxy_route_retried":False,"reason":"same loopback proxy and previously confirmed refusal; no bypass or settings change"},"MOA_attachment":{"browser_error":"net::ERR_BLOCKED_BY_CLIENT","approved_web_retrieval_error":"400 Unsupported content-type: application/octet-stream","bytes_obtained":False},"policy_changes":False,"security_controls_changed":False})

write_json("crawl_execution_manifest.json", {"phase":"RAG v2 Phase 20.1E Exec r3 Step 3E","checked_at_utc":now(),"workspace":str(ROOT),"staging_root":str(STAGE),"report_root":str(OUT),"source_scope":"official Taiwan aquaculture, government, Fisheries Agency, TFRI; six target fish; controlled navigation only","sites_opened":3,"official_pages_opened":len(page_rows),"official_file_links_discovered":len(attachment_links),"download_attempts":{"browser":8,"approved_web_retrieval_connector":1,"total_methods":9},"downloaded_pdf_count":len(integrity_rows),"unique_new_files_in_my_data":sum(bool(x.get("staged_path")) for x in download_rows),"duplicate_download_references":len(duplicate_rows),"raw_html_files":0,"browser_view_only_page_count":len(page_rows),"max_concurrency":1,"recursive_site_crawl":False,"formal_source_admission":0,"corpus_rebuild":0,"e4_rebuild":0,"benchmark_questions_created":0,"model_evaluations":0,"winner":None,"source_registry_input":"Phase20.1E Step3C and Step3D; 9 pending plus prior registry and added FA sea-cage seed"})

write_json("source_duplicate_registry.json", {"duplicate_count":len(duplicate_rows),"duplicates":duplicate_rows,"rule":"Identical SHA-256 bytes are referenced by path only; no duplicate copy was stored in staging."})

# Frozen checksums from Step 3D compatibility, re-evaluated against the current workspace.
compat_in=json.loads((BASE/"step3d_source_intake/compatibility.json").read_text(encoding="utf-8-sig"))
anchors=[]
for old in compat_in.get("frozen_anchor_checks",[]):
    p=ROOT/old["path"]
    exists=p.is_file()
    actual=sha(p) if exists else None
    st=p.stat() if exists else None
    anchors.append({"name":old["name"],"path":old["path"],"expected_sha256":old.get("expected_sha256"),"actual_sha256":actual,"sha256_match":bool(exists and actual==old.get("expected_sha256")),"exists":exists,"size_bytes":st.st_size if st else None,"expected_size_bytes":old.get("expected_size_bytes"),"mtime_ns":st.st_mtime_ns if st else None,"expected_mtime_ns":old.get("expected_mtime_ns")})
model_expected=compat_in.get("ollama_frozen_model_digests",{}).get("expected_from_step3c",{})
model_actual=None; model_error=None
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=4) as response:
        tags=json.loads(response.read().decode("utf-8"))
        model_actual={x.get("name"):x.get("digest") for x in tags.get("models",[])}
except Exception as e:
    model_error=repr(e)
model_checks=[]
for name,expected in model_expected.items():
    actual=next((v for k,v in (model_actual or {}).items() if k==name or k.split(":")[0]==name.split(":")[0]),None)
    model_checks.append({"model":name,"expected_digest":expected,"actual_digest":actual,"match":actual==expected if actual else None})
write_json("compatibility.json", {"checked_at_utc":now(),"protected_anchor_checks":anchors,"all_anchors_match":all(x["sha256_match"] for x in anchors),"ollama_digest_checks":model_checks,"ollama_get_error":model_error,"sqlite":{"path":"rag_store.sqlite3","size_bytes":next((x["size_bytes"] for x in anchors if x["name"]=="rag_store_sqlite3"),None),"mtime_ns":next((x["mtime_ns"] for x in anchors if x["name"]=="rag_store_sqlite3"),None),"sha256":next((x["actual_sha256"] for x in anchors if x["name"]=="rag_store_sqlite3"),None),"read_only_access":True,"quick_check":"not rerun; prior Step3D quick_check=ok"},"phase15_20_protected_files":{"previous_comprehensive_count":636,"previous_mismatches":0,"current_step":"No writes to protected report paths; current content hashes for 11 frozen corpus/index/E4/SQLite anchors rechecked. Comprehensive 636-file rehash not independently rerun."},"phase20_1_historical_reports":"read-only; no overwrite","production_http_smoke":"not_tested","production_app_modified":False,"corpus_modified":False,"indexes_modified":False,"formal_source_admissions":0,"formal_corpus_rebuilds":0,"formal_e4_rebuilds":0,"benchmark_questions_created":0,"model_scoring_requests":0,"winner":None,"my_data_staging":{"new_file_count":sum(bool(x.get("staged_path")) for x in download_rows),"auto_ingestion_watcher_found":False,"manual_build_index_scans_staged_pdf":True,"scan_rule":"rag_core.py build_index recursively includes DATA_DIR.rglob files with .pdf/.doc/.docx/.odt/.txt/.md; no watcher detected; no build_index/start_rag executed"}})

write_json("source_version_comparison.json", {"checked_at_utc":now(),"items":[
    {"source_id":"MOA-LAW-FL035443","parent_consolidated_revision":"2025-01-08","Annex_I_revision_observed_in_law_history":"2019-04-22","current_attachment_bytes_match":"unknown; browser attachment request blocked and no bytes obtained","conclusion":"Do not infer current Annex I item-specific authorization from parent revision date."},
    {"source_id":"TFRIN-MANUAL17","official_page_publication":"2023-08-31","official_page_modified":"2025-12-09","browser_downloads_match_existing_files_by_sha256":True,"PDF published/revision linkage":"exact file bytes match local copies; page modified date is not itself a PDF revision date","rights":"permission required per page notice; not obtained"},
    {"source_id":"TFRIN-GROUPER-DISEASE","official_page_date":"2017-12-01","official_page_modified":"2021-07-13","downloaded_pdf_page_count":10,"PDF internal creation/modification":"2017 metadata reported by pdfinfo; exact official page attachment link observed"},
    {"source_id":"TFRIN-TILAPIA-ARTICLE","official_publication":"2008-12-31","issue":"16(2)","pages":"41-47","catalog_attachment_hash_matches_local_pdf":True,"scope":"named tilapia strains and stated 364-day culture conditions"},
    {"source_id":"FA-HAZARD/FA-SEA-CAGE/FA-COLD","version":"page content observed in browser; no local raw HTML/PDF; exact content snapshot/version checksum unavailable"},
    {"source_id":"TFRIN-MILKFISH-COLD/TFRIN-FCR-EXPLAIN/TFRIN-EEL-QA/TFRIN-EEL-FRY","version":"browser-view pages; no raw HTML bytes saved; page/footer dates do not substitute for archived content checksum"}
]})

# Re-emit the remaining gap and admission reports after all source facts are available.
write_json("source_admission_review_queue_summary.json", {"ready_for_admission_review":["TFRIN-GROUPER-DISEASE","TFRIN-TILAPIA-ARTICLE"],"needs_rights_review":["TFRIN-MANUAL17"],"awaiting_original_or_version":["MOA-LAW-FL035443"],"browser_view_only_requires_content_freeze":["FA-HAZARD","FA-SEA-CAGE","FA-COLD","TFRIN-MILKFISH-COLD","TFRIN-FCR-EXPLAIN","TFRIN-EEL-QA","TFRIN-EEL-FRY"],"rejected_or_out_of_scope":["TFRIN-SGR-FCR"],"formal_admissions":0,"ready_for_admission_review_does_not_mean_admitted":True})

readiness=json.loads((BASE/"step3c_evidence_expansion/readiness_after_step3c.json").read_text(encoding="utf-8-sig"))
write_json("readiness_after_step3e.json", {**readiness,"checked_at_utc":now(),"new_official_source_files_staged":sum(bool(x.get("staged_path")) for x in download_rows),"new_existing_silver_units":0,"external_admitted_ready":0,"normal_risk_ready_units":11,"normal_evidence_ready":False,"medication_law_verified_ready_units":0,"high_risk_ready":False,"calculation_verified_ready_units":0,"calculation_ready":False,"phase20_2_benchmark_construction_ready":False,"winner":None,"reason":"New source files remain staged or browser-view only; no corpus admission or evidence-unit promotion occurred."})

write_json("source_admission_review_queue.json", {"generated_at_utc":now(),"entries":[{"source_id":x["source_id"],"title":x["title"],"url":x["landing"],"status":x["status"],"blocker":x["blocker"],"formal_admitted":False} for x in official_sources]})

write_json("crawl_execution_manifest.json", {"phase":"RAG v2 Phase 20.1E Exec r3 Step 3E","checked_at_utc":now(),"workspace":str(ROOT),"staging_root":str(STAGE),"report_root":str(OUT),"source_scope":"official Taiwan aquaculture, government, Fisheries Agency, TFRI; six target fish; controlled navigation only","sites_opened":3,"official_pages_opened":len(page_rows),"official_file_links_discovered":len(attachment_links),"download_attempts":{"browser":8,"approved_web_retrieval_connector":1,"total_methods":9},"downloaded_pdf_count":len(integrity_rows),"unique_new_files_in_my_data":sum(bool(x.get("staged_path")) for x in download_rows),"duplicate_download_references":len(duplicate_rows),"raw_html_files":0,"browser_view_only_page_count":len(page_rows),"max_concurrency":1,"recursive_site_crawl":False,"formal_source_admission":0,"corpus_rebuild":0,"e4_rebuild":0,"benchmark_questions_created":0,"model_evaluations":0,"winner":None,"source_registry_input":"Phase20.1E Step3C and Step3D; all 9 Step3D pending entries, remaining Step3A scope records, and FA sea-cage seed"})

summary = f'''# Phase 20.1E Exec r3 — Step 3E Summary

Execution time: {now()}

## Browser and acquisition

- Official hosts opened: 3 (law.moa.gov.tw, fa.gov.tw, tfrin.gov.tw).
- Official pages opened: {len(page_rows)}. The pages were read in the Codex In-app Browser; no raw HTML bytes were saved, so these are `browser_view_only` observations.
- Official file links recorded: {len(attachment_links)} (including two Manual 17 sections outside the six target species, retained as discovery-only links).
- PDF downloads that yielded local bytes: {len(integrity_rows)}; valid PDF signature/open/page extraction: {sum(x['valid'] for x in integrity_rows)}.
- New unique file staged under `my_data`: {sum(bool(x.get('staged_path')) for x in download_rows)}. Duplicate references: {len(duplicate_rows)}; no duplicate PDF bytes were stored.
- HTML raw-byte files staged: 0. Quarantine contains no successful or corrupt downloads; MOA attachment bytes were never obtained.

## New file actually added to `my_data`

`my_data/_official_source_staging/phase20_1E_step3E/raw/pdf/07石斑魚養殖疾病防疫.pdf` — 13,558,981 bytes; SHA-256 `74cab196d89b6f22b5b029f6bd8fcbfa56df214de2901e876f19b9ee2897c6b5`; valid PDF, 10 pages, extractable text on all pages. Official page: https://www.tfrin.gov.tw/theme_data.php?id=242&theme=aquatic_technology. Use: potential grouper-disease evidence source; not yet admitted and not yet promoted to a Silver unit. Rights and proposition-level verification remain open.

Six other PDFs downloaded from TFRI official links were byte-identical to files already under `my_data` (Manual 17 full lower volume; 金目鱸, 七星鱸, 石斑魚, 烏魚 sections; and the tilapia research paper). They are registered as SHA-256 duplicate references; no duplicate copies were staged. The browser-download copies remain in the user Downloads folder.

## Network and source blockers

- Shell proxy environment still points to `127.0.0.1:9`; prior logs show `ConnectionRefusedError / WinError 10061` at TCP connect, before TLS or HTTP. The same route was not retried.
- The Codex browser could read official pages and download TFRI PDFs via official attachment links. MOA Annex I could not be downloaded: browser reported `net::ERR_BLOCKED_BY_CLIENT`; the approved web retrieval connector reported `400 Unsupported content-type: application/octet-stream`. No proxy/security bypass was used.
- FA cold pages and TFRI Q&A/FCR/eel pages were visible in the browser but had no downloaded original HTML/PDF bytes. They remain browser-view-only and require a content/version freeze before admission review.

## Evidence implications

- Existing Evaluation Corpus v2, E1/E2 and Historical E4 remain unchanged. No new unit was formally admitted or counted.
- Formal readiness remains normal-risk 11/120 (shortfall 109), Medication/Law 0/30, Calculation 0/30; total formal target 180, shortfall 169. Phase 20.2 readiness remains false; Winner remains null.
- Sources suitable to enter a separate admission review: TFRIN grouper-disease PDF (new staged original) and TFRIN tilapia paper (official attachment SHA matches existing local PDF), with the limitations in the review queue. Manual 17 requires rights review; MOA requires Annex I bytes/version; browser-view sources require a reproducible local content snapshot.

## `my_data` ingestion isolation

No ingestion watcher was found. Production `rag_core.py` `build_index()` recursively scans `my_data` and includes `.pdf`; `start_rag.ps1` only calls `build_index.py` if `rag_store.sqlite3` is absent. No indexer or production app was run. Because staging is inside `my_data`, a future explicit `build_index.py` run would see the staged PDF; keep this staging excluded from formal ingestion until a separately approved admission step.

## Compatibility and scope

- 11 frozen corpus/index/E4/SQLite anchors rechecked; see `compatibility.json`.
- Production HTTP smoke: not tested.
- Formal source admissions: 0. Corpus/E4 rebuilds: 0. Benchmark questions: 0. Model evaluations: 0. Winner: null.
'''
(OUT/"step3e_summary.md").write_text(summary,encoding="utf-8")

write_json("browser_capability_preflight.json", {"checked_at_utc":now(),"available_browser":"Codex In-app Browser via unified-computer-use cua_repl","browser_tab_navigation":"pass","dom_accessibility_read":"pass","official_pdf_native_download":"pass (7 PDFs)","browser_dom_only_pages":len(page_rows),"raw_html_saved":False,"dedicated_browser_tool":"no separate browser MCP tool surfaced; CUA browser was callable","local_file_access":"PowerShell verified Downloads and staging paths","sandbox_write":"pass for new workspace staging and report paths","limitations":["MOA Download.ashx blocked by browser net::ERR_BLOCKED_BY_CLIENT.","Browser download operation did not expose final redirect URL for files."]})

print(json.dumps({"pages":len(page_rows),"links":len(attachment_links),"downloaded":len(integrity_rows),"valid":sum(x["valid"] for x in integrity_rows),"duplicates":len(duplicate_rows),"unique_staged":sum(bool(x.get("staged_path")) for x in download_rows),"report_dir":str(OUT)},ensure_ascii=False))
