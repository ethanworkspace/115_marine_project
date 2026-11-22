import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path.cwd()
BASE = ROOT / "reports/evaluation/final_model_selection/phase20_1E_exec_r3"
OUT = BASE / "step3c_evidence_expansion"
OUT.mkdir(parents=True, exist_ok=True)
STAMP = datetime.now(timezone.utc).isoformat()

def jread(path):
    return json.loads(path.read_text(encoding="utf-8"))

def jlread(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fsha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).replace("", "").replace("", ""))

def write_json(name, obj):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def write_jsonl(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

s2 = jread(BASE / "step2_existing_corpus/screening_processing_report.json")
pilot = jlread(BASE / "step2b_verification_pilot/verification_pilot_candidates.jsonl")
old_units = jlread(BASE / "step2b_verification_pilot/promoted_evidence_units.jsonl")
s3b = jlread(BASE / "step3b_source_review/existing_corpus_candidate_review.jsonl")
source_rows = jlread(BASE / "step3b_source_review/official_source_review_registry.jsonl")
s3b_ready = jread(BASE / "step3b_source_review/readiness_after_step3b.json")
law0 = jread(BASE / "step3b_source_review/medication_law_review.json")
calc0 = jread(BASE / "step3b_source_review/calculation_review.json")
candidates = s2["per_candidate"]
candidate_by_id = {x["candidate_id"]: x for x in candidates}
corpus = {x["chunk_id"]: x for x in jlread(ROOT / "data/evaluation/corpus_v2.jsonl")}
assert sum(x["candidate_processing_status"] == "needs_review" for x in candidates) == 317
assert len(source_rows) == 11 and sum(x.get("review_decision") != "rejected" for x in source_rows) == 9
assert s3b_ready["existing_silver_ready"] == 7 and s3b_ready["winner"] is None

# outcome, review rationale, exact phrase used as a page-location check
D = {
"chunk_8e445aa508115289b306fc80f8f62854":("needs_review","Background/global context is not a sufficiently scoped atomic Taiwan fact; the study stock-history clause is reviewed separately.","尼羅吳郭魚"),
"chunk_d3fa6bb110cf5c619aaf34078dcc9809":("needs_review","Original PDF hash/page/span match, but frozen corpus source_verified=false and ingestion_status=accepted_with_warning; existing strict source-identity gate is not met.","N1 品系是1966 年引進"),
"chunk_9e01efee566c5dbba22615ccd9fc54a7":("needs_review","Original PDF hash/page/span match, but frozen corpus source_verified=false and ingestion_status=accepted_with_warning; existing strict source-identity gate is not met.","養殖水溫範圍約21 ~ 31 ℃"),
"chunk_7f4ec0508170523ba5b3e3db1415a05a":("rejected","Body-weight/morphometrics table, not water-quality evidence.","Table 6"),
"chunk_cbf8916f55f55aaebeb5a1ecc6b00220":("rejected","Growth performance table (SGR/WG/FCR/survival), not water-quality evidence.","Growth performance"),
"chunk_911f1b92a07b5652baebe49271211d84":("rejected","Temperature/salinity passage concerns white shrimp; mullet is only named as a co-culture species.","白蝦"),
"chunk_19c2bf51d45c503d9593d3720dea6762":("needs_review","OCR/page text is degraded and concerns reproduction; no Water Quality unit is supported.","性腺"),
"chunk_159dac7147ad554b9e9fb64749d1edff":("needs_review","Shade/temperature statement is generic and does not establish grouper applicability.","遮蔽"),
"chunk_9e7d75da64045637a2a0209ef818e4c8":("rejected","Shrimp feed/residual-feed passage; wrong subject for grouper Fact.","白蝦"),
"chunk_eb374baf88dd547688fe771539a342e9":("rejected","Solar-panel/bird-control passage; not a grouper fact.","鳥"),
"chunk_ece437132d545224a3d7bacda20bfe6e":("needs_review","Generic pond preparation lacks explicit grouper applicability and an atomic WQ proposition.","整池"),
"chunk_2e4df5f09b2a59dc81bdac4f27ae77d0":("needs_review","Same generic pond-preparation knowledge group as chunk_ece437132d545224a3d7bacda20bfe6e; applicability absent.","整池"),
"chunk_b28f08210aa6594e8295762a0abdf693":("rejected","White-shrimp harvest content; wrong subject for grouper water quality.","白蝦"),
"chunk_f65375ceb56f5daf94a748ef00689b3e":("rejected","Text identifies 午仔魚, not grouper.","午仔魚"),
"chunk_936cc1cd031454fa9ab5d754225ad180":("needs_review","Original PDF hash/page/span match, but frozen corpus source_verified=false and ingestion_status=accepted_with_warning; existing strict source-identity gate is not met.","鰻魚則以感染體軀後段及尾部為主"),
"chunk_70f1227b5c4f53ff85e347c63e4988a5":("needs_review","Original PDF hash/page/span match, but frozen corpus source_verified=false and ingestion_status=accepted_with_warning; existing strict source-identity gate is not met.","在12－3 月低水溫期的黴菌性疾病則以水黴病為主"),
"chunk_3c1310048516502595a2f6053f63a93b":("needs_review","Original PDF hash/page/span match, but frozen corpus source_verified=false and ingestion_status=accepted_with_warning; existing strict source-identity gate is not met.","此症狀常見於養殖之日本白鰻"),
"chunk_7a1fb9756cb75361a957402d7c996188":("needs_review","Historical 1989 disease grouping; domain review needed before use as current taxonomy.","1989"),
"chunk_07e5fdceca215e158b34d1d39c3fa3cc":("rejected","General pond-fish/shrimp gas-bubble disease with no eel-specific applicability.","氣泡病"),
"chunk_d98080b6631351a380ce1f25a3ab6597":("rejected","General farmed-fish/shrimp disease passage lacks eel-specific applicability.","養殖魚"),
"chunk_26f70d54a0235360b20ce887b17cf94f":("rejected","Bibliographic/reference material only; no answerable proposition.","參考文獻"),
"chunk_f1f5b5f68c8f597b9c6381c51bd235cd":("rejected","Title/imprint page only; no atomic fact.","鰻魚養殖之健康管理"),
"chunk_7d0abf0cedee5d1a8c5f07bf469c0c39":("rejected","Reference list only; no supportable evidence proposition.","參考文獻"),
"chunk_fed39712f8315657818afe6b6ccb21fe":("needs_review","Combines winter preparation, temperature and disease-risk claims; category and atomic boundaries unresolved.","冬季"),
"chunk_1736f8295f1a5e9e95062eb0ab3f2a31":("needs_review","Generic pond preparation is not a distinct measurable WQ fact and needs category review.","清理"),
"chunk_a112858ddbd9509cb5c5467cfc075e75":("silver_ready","Official 2025 Golden Seabass Biosecurity Handbook title page, frozen source hash, physical page and pathogen list verified.","Vibrio alginolyticus"),
"chunk_f0e6bf999e5d502cb38c1a639368222d":("silver_ready","Official 2025 Golden Seabass Biosecurity Handbook title page, frozen source hash, physical page and Aeromonas list verified.","Aeromonas hydrophila"),
"chunk_a8d5fca762b85ff0ae8df896182f6ba1":("silver_ready","Official 2025 Golden Seabass Biosecurity Handbook title page, frozen source hash, physical page and Trichodina list verified.","Trichodina spp."),
"chunk_9c9785c071cb5588b40e2ef5dc167a25":("silver_ready","Official 2025 Golden Seabass Biosecurity Handbook title page, frozen source hash, physical page and Dactylogyriasis pathogen list verified.","Gyrodactylus spp."),
"chunk_bc64e9838cac5ff4bb12792c052d97ad":("needs_review","Clinical/transmission excerpt lacks a reliable disease heading; claim-to-disease binding is ambiguous.","傳播途徑"),
"chunk_bec71c2e80f4575abfab9afee6f880e2":("needs_review","Preface lists several diseases broadly; no single atomic claim is promoted.","常見病原"),
"chunk_eb76c454db4058058d051a6044082da9":("rejected","Text identifies 七星鱸, not 金目鱸; species mismatch.","七星鱸"),
"chunk_d76db7c1db4d5968be9659da5aaf0478":("needs_review","Graph excerpt lacks full axis/time context for an unambiguous water-quality value.","總磷"),
"chunk_b898e8a2f98055faa5cba121d6797638":("rejected","Feeding management passage, not water-quality evidence.","投餵"),
}
assert len(D) == 34
pilot_ids = {x.get("candidate_id") or x.get("chunk_id") for x in pilot}
s3b_ids = {x.get("chunk_id") for x in s3b if x.get("chunk_id")} | {x.get("candidate_id") for x in s3b}
excluded_overlap = "chunk_72fbed1cd9645a9bb3b820731edf6c08"
assert excluded_overlap in pilot_ids and not (set(D) & (pilot_ids | s3b_ids))

pdf_by_sha = {}
for folder in (ROOT / "my_data", ROOT / "data"):
    if folder.exists():
        for p in folder.rglob("*.pdf"):
            try:
                pdf_by_sha.setdefault(fsha(p), p)
            except OSError:
                continue

decisions = []
page_text_by_id = {}
for cid, (status, reason, phrase) in D.items():
    r = candidate_by_id[cid]
    src = r["source"]
    c = corpus[cid]
    local = pdf_by_sha.get(src["source_checksum"])
    assert local is not None and fsha(local) == src["source_checksum"]
    pdf = pymupdf.open(local)
    page_num = int(src["page"])
    assert 1 <= page_num <= len(pdf)
    page_text = pdf[page_num - 1].get_text("text")
    pdf.close()
    text = c.get("text", "")
    assert norm(text) in norm(page_text), f"frozen chunk not found on PDF page: {cid}"
    assert sha(text.encode("utf-8")) == src["content_checksum"]
    assert c.get("retrieval_role") == "retrieval" and c.get("benchmark_eligible") is True
    assert r["candidate_processing_status"] == "needs_review"
    page_text_by_id[cid] = page_text
    decisions.append({
        "candidate_id": cid, "original_id": r.get("original_id", cid),
        "source_screening_status": r.get("original_screening_status"), "step2_status": r["candidate_processing_status"],
        "species": r.get("original_species"),
        "category": {"fact":"Fact","water_quality":"Water Quality","disease":"Disease","climate":"Climate / Cold"}.get(r.get("original_category"), r.get("original_category")),
        "document_id": src["document_id"], "chunk_id": cid, "page_pdf_1based": page_num,
        "source_title": src["source_title"], "source_pdf_path": str(local.relative_to(ROOT)),
        "source_pdf_sha256_expected": src["source_checksum"], "source_pdf_sha256_actual": fsha(local),
        "source_pdf_sha256_match": True, "chunk_sha256_expected": src["content_checksum"],
        "chunk_sha256_actual": sha(text.encode("utf-8")), "chunk_sha256_match": True,
        "frozen_retrieval_role": c.get("retrieval_role"), "frozen_benchmark_eligible": c.get("benchmark_eligible"),
        "frozen_source_verified": c.get("source_verified"), "frozen_ingestion_status": c.get("ingestion_status"),
        "chunk_text_found_on_original_pdf_page": True, "support_probe_phrase": phrase,
        "support_probe_found": norm(phrase) in norm(page_text), "decision": status,
        "decision_reason": reason, "human_reviewed": False, "corpus_eligibility_modified": False
    })
outcome_counts = Counter(x["decision"] for x in decisions)
assert outcome_counts == Counter({"silver_ready":4,"needs_review":16,"rejected":14})

# Twelve direct, scoped propositions from nine reviewed candidates.
specs = [
("chunk_d3fa6bb110cf5c619aaf34078dcc9809","Fact","該研究所稱 N1 尼羅吳郭魚品系於 1966 年引進臺灣。","N1 品系是1966 年引進","N1 line introduction year","僅限論文所述 N1 試驗品系，不外推所有尼羅吳郭魚品系。","2008; Journal of Taiwan Fisheries Research 16(2):41-47"),
("chunk_d3fa6bb110cf5c619aaf34078dcc9809","Fact","該研究所稱 N2 尼羅吳郭魚品系於 2002 年引進臺灣。","N2 品系是2002 年引進","N2 line introduction year","僅限論文所述 N2 試驗品系。","2008; Journal of Taiwan Fisheries Research 16(2):41-47"),
("chunk_d3fa6bb110cf5c619aaf34078dcc9809","Fact","該研究所稱歐利亞吳郭魚試驗品系 A 於 1974 年引進。","歐利亞吳郭魚 (O. aureus) (A) 則是1974 年引進","O. aureus test-line introduction year","僅限該論文 A 試驗品系，不外推一般族群。","2008; Journal of Taiwan Fisheries Research 16(2):41-47"),
("chunk_9e01efee566c5dbba22615ccd9fc54a7","Water Quality","該論文報告其全期吳郭魚養殖試驗的水溫範圍約為 21–31 °C。","養殖水溫範圍約21 ~ 31 ℃","tilapia trial water-temperature range","僅限該論文全期試驗與所述條件；不是通用適溫建議。","2008; Journal of Taiwan Fisheries Research 16(2):41-47"),
("chunk_9e01efee566c5dbba22615ccd9fc54a7","Fact","該論文報告 N2×N2 組在全期試驗中的平均日增重最高，為 2.5 g/day。","WG 以N2 × N2 組最高，為2.5 g/day","tilapia trial WG result for N2xN2","限於該論文品系、試驗條件及約一年的試驗。","2008; Journal of Taiwan Fisheries Research 16(2):41-47"),
("chunk_936cc1cd031454fa9ab5d754225ad180","Disease","該疾病手冊記載，水黴病在鰻魚主要感染體軀後段及尾部。","鰻魚則以感染體軀後段及尾部為主","eel water-mold affected body region","手冊描述的鰻魚病例；來源陳述，不代表個案診斷。","水產試驗所特刊第2號; year unknown in local imprint"),
("chunk_70f1227b5c4f53ff85e347c63e4988a5","Disease","該 2006 年臺灣鰻魚病例分析記載，12–3 月低水溫期以水黴病為主。","在12－3 月低水溫期的黴菌性疾病則以水黴病為主","eel fungal disease seasonal observation","限於該文分析的歷史鰻魚病例與月份分類；非當前疾病預測。","水產試驗所特刊第8號, 2006; article pp.75-84"),
("chunk_3c1310048516502595a2f6053f63a93b","Disease","該 2006 年手冊指出，此處描述的寄生蟲病症狀常見於養殖日本白鰻。","此症狀常見於養殖之日本白鰻","Japanese white eel parasite symptom observation","限於來源指出的養殖日本白鰻與症狀描述；不得單獨用於診斷。","水產試驗所特刊第8號, 2006; article pp.13-50"),
("chunk_a112858ddbd9509cb5c5467cfc075e75","Disease","金目鱸生物安全手冊在弧菌感染症病原段列出溶藻弧菌、哈威氏弧菌及創傷弧菌。","(Vibrio alginolyticus) 溶藻弧菌 哈威氏弧菌 (V. harveyi ) 病原 創傷弧菌 (V. vulnificus)","golden seabass vibriosis pathogen list","金目鱸手冊弧菌感染症段落；來源列舉，不代表排他性病原清單。","金目鱸養殖生物安全手冊; 2025"),
("chunk_f0e6bf999e5d502cb38c1a639368222d","Disease","金目鱸生物安全手冊在產氣單胞菌感染症病原段列出 Aeromonas hydrophila 與 A. veronii。","(Aeromonas hydrophila) 親水性產氣單胞菌 維隆氣單胞菌 (A. veronii) 病原","golden seabass aeromoniasis pathogen list","金目鱸手冊病原段所列，不外推至其他魚種。","金目鱸養殖生物安全手冊; 2025"),
("chunk_a8d5fca762b85ff0ae8df896182f6ba1","Disease","金目鱸生物安全手冊在車輪蟲感染症病原段列出 Trichodina spp. 及 Trichodinella spp.。","Trichodina spp.， Trichodinella spp.","golden seabass trichodinosis genus list","金目鱸手冊病原段所列屬級分類。","金目鱸養殖生物安全手冊; 2025"),
("chunk_9c9785c071cb5588b40e2ef5dc167a25","Disease","金目鱸生物安全手冊在指環蟲感染症病原段稱 Gyrodactylus spp. 與 Dactylogyrus spp. 最常見。","以Gyrodactylus spp. 及Dactylogyrus spp. 最常見","golden seabass dactylogyriasis pathogen genera","金目鱸手冊指環蟲感染症段，保留原文限定語。","金目鱸養殖生物安全手冊; 2025"),
]
units=[]
fingerprints=set()
decision_by_id={x["candidate_id"]:x for x in decisions}
old_facts={norm(x.get("atomic_fact_or_rule","")) for x in old_units}
for cid,cat,claim,span,fact_key,app,version in specs:
    d=decision_by_id[cid]
    assert norm(span) in norm(page_text_by_id[cid]), (cid,span)
    fp=sha((d["species"]+"|"+cat+"|"+norm(fact_key)).encode())
    assert fp not in fingerprints
    fingerprints.add(fp)
    assert norm(claim) not in old_facts
    if d["frozen_source_verified"] is not True or d["frozen_ingestion_status"] != "accepted":
        continue
    state="official title/imprint and source checksum verified from local original PDF; landing-page-to-byte binding remains a separate review"
    if cid in {"chunk_a112858ddbd9509cb5c5467cfc075e75","chunk_f0e6bf999e5d502cb38c1a639368222d","chunk_a8d5fca762b85ff0ae8df896182f6ba1","chunk_9c9785c071cb5588b40e2ef5dc167a25"}:
        state="official 2025 TFRIN handbook title page and frozen source hash match"
    units.append({
        "evidence_unit_id":"eu_step3c_"+sha((cid+"|"+fp).encode())[:20],"candidate_id":cid,
        "species":d["species"],"category":cat,"risk_level":"normal","atomic_fact_or_rule":claim,
        "support_span":span,"support_start":None,"support_end":None,"chunk_id":cid,"document_id":d["document_id"],
        "page_pdf_1based":d["page_pdf_1based"],"source_title":d["source_title"],"source_status":state,
        "source_version":version,"source_pdf_sha256":d["source_pdf_sha256_actual"],
        "chunk_sha256":d["chunk_sha256_actual"],"applicability":app,"duplicate_group_id":"fact_"+fp[:18],
        "source_verified_step3c":d["frozen_source_verified"],"ingestion_status_step3c":d["frozen_ingestion_status"],
        "readiness_status":"silver_ready",
        "verification_method":"Read-only original PDF SHA-256, extracted PDF page, exact normalized support-span match, frozen chunk SHA-256, retrieval eligibility, direct claim/category/species-scope review.",
        "human_reviewed":False,"notes":"Corpus-Grounded Silver; not Human Gold. No corpus eligibility or source admission changed."
    })
assert len(units)==4

species=["虱目魚","吳郭魚","石斑魚","鱸魚","烏魚","鰻魚"]
categories=["Fact","Water Quality","Disease","Climate / Cold","Safe Medication / Law","Calculation"]
def catnorm(x):
    return {"fact":"Fact","water_quality":"Water Quality","disease":"Disease","climate":"Climate / Cold","calculation":"Calculation","medication_law":"Safe Medication / Law"}.get(x,x)
def count_units(rows):
    out=Counter()
    for x in rows:
        sp=x.get("species"); ca=catnorm(x.get("category"))
        if sp in species and ca in categories: out[(sp,ca)]+=1
    return out
oldc,newc=count_units(old_units),count_units(units)
screen=Counter(); elig=Counter()
for x in candidates:
    sp=x.get("original_species"); ca=catnorm(x.get("original_category"))
    if sp in species and ca in categories:
        screen[(sp,ca)]+=1
        c=corpus.get(x["candidate_id"],{})
        if c.get("retrieval_role")=="retrieval" and c.get("benchmark_eligible") is True: elig[(sp,ca)]+=1
matrix=[]
for sp in species:
    for ca in categories:
        k=(sp,ca); b=oldc[k]; n=newc[k]; total=b+n; short=max(0,5-total)
        status="READY_5_PLUS" if total>=5 else ("PARTIAL_1_TO_4" if total else "NO_EVIDENCE")
        gap="no_screened_candidate" if not screen[k] else ("screened_candidates_exist_but_none_passed_all_evidence_gates" if not total else ("existing_evidence_partial; source_strengthening_still_needed" if short else "target_met_for_this_cell; other_cells_open"))
        matrix.append({"species":sp,"category":ca,"status":status,"target_count":5,
            "screened_candidate_count":screen[k],"retrieval_eligible_screening_candidate_count":elig[k],
            "baseline_ready":b,"new_existing_corpus_silver_ready":n,"new_external_staged_candidates":0,
            "external_admitted_ready":0,"total_formal_ready":total,"remaining_shortfall":short,
            "source_review_status":"existing_corpus_evidence_verified" if total else ("candidate_reviewed_no_promotion" if screen[k] else "source_discovery_needed"),
            "source_gap_classification":gap,"structurally_infeasible":False,"infeasibility_assessed":False})
assert len(matrix)==36 and sum(x["baseline_ready"] for x in matrix)==7
assert sum(x["new_existing_corpus_silver_ready"] for x in matrix)==4
ready5=sum(x["status"]=="READY_5_PLUS" for x in matrix)
partial=sum(x["status"]=="PARTIAL_1_TO_4" for x in matrix)
empty=sum(x["status"]=="NO_EVIDENCE" for x in matrix)
assert (ready5,partial,empty)==(1,5,30)

# Nine pending official-source handoffs; two rejected source leads remain excluded.
source_by={x["source_id"]:x for x in source_rows}
priority=["MOA-LAW-FL035443","FA-HAZARD","FA-COLD","TFRIN-MILKFISH-COLD","TFRIN-GROUPER-DISEASE","TFRIN-MANUAL17","TFRIN-TILAPIA-ARTICLE","TFRIN-SGR-FCR","TFRIN-FCR-EXPLAIN"]
coverage={
"MOA-LAW-FL035443":{"species":species,"categories":["Safe Medication / Law"]},
"FA-HAZARD":{"species":["虱目魚","吳郭魚","石斑魚","鱸魚"],"categories":["Climate / Cold"]},
"FA-COLD":{"species":["虱目魚","吳郭魚"],"categories":["Climate / Cold"]},
"TFRIN-MILKFISH-COLD":{"species":["虱目魚"],"categories":["Disease","Climate / Cold"]},
"TFRIN-GROUPER-DISEASE":{"species":["石斑魚"],"categories":["Disease"]},
"TFRIN-MANUAL17":{"species":["石斑魚","烏魚"],"categories":["Disease","Water Quality","Climate / Cold"]},
"TFRIN-TILAPIA-ARTICLE":{"species":["吳郭魚"],"categories":["Fact","Climate / Cold"]},
"TFRIN-SGR-FCR":{"species":[],"categories":["Calculation"],"note":"Silver croaker fry source; reference only pending target-species applicability."},
"TFRIN-FCR-EXPLAIN":{"species":species,"categories":["Calculation"],"note":"General explainer; complete deterministic formula details absent."}}
packets=[]
for rank,sid in enumerate(priority,1):
    r=source_by[sid]; url=r.get("official_url") or ""
    exact=url if ("redirect_files.php" in url or url.lower().endswith(".pdf")) else None
    packets.append({"priority":rank,"source_id":sid,"official_title":r.get("source_title"),
        "issuing_authority":r.get("issuing_authority"),"official_landing_url":url,"exact_document_url":exact,
        "expected_document_type":r.get("document_type"),"target_species_and_categories":coverage[sid],
        "required_version_or_effective_date":r.get("effective_date") if r.get("effective_date") not in ("unknown",None) else r.get("revision_date","unknown"),
        "existing_local_candidate":r.get("local_file_reference"),"existing_candidate_sha256":r.get("document_sha256"),
        "reason_current_candidate_insufficient":r.get("blocking_reason"),
        "manual_acquisition_instructions":"Use an organization-approved browser/network to save the official original PDF or reproducible HTML snapshot unchanged; preserve landing URL, exact file URL, retrieval date and version/date, then provide through approved workspace handoff. No mirror or proxy bypass.",
        "rights_or_usage_restrictions":"unknown; verify official source reuse notice before staging/admission" if sid!="TFRIN-MANUAL17" else "Official page notes reproduction/digitization/reprint requires permission; resolve permission and version linkage before admission.",
        "required_checksum_and_page_verification":"SHA-256 original bytes; verify title/authority/version against official source; record physical and printed page/section; locate exact support span; verify species/topic applicability.",
        "download_blocker":"Step3B recorded configured proxy 127.0.0.1:9 TCP ConnectionRefusedError / WinError 10061 before TLS/HTTP; no bypass or new download attempted in Step3C.",
        "current_review_decision":r.get("review_decision"),"status":"blocked_needs_manual_original_or_version_review",
        "downloaded_this_step":False,"new_document_sha256":None})
assert len(packets)==9

# Context-only audit: do not edit any frozen eligibility label.
ctx_rows=[]
for r in s3b:
    cid=r.get("chunk_id"); c=corpus.get(cid,{}) if cid else {}
    role=c.get("retrieval_role",r.get("corpus_retrieval_role")); ctx=role=="context_only"
    if r.get("candidate_id")=="targeted_7400f262ec2de577":
        rem=["bind local one-page PDF to currently served Fisheries Agency version","verify rights and exact version","future corpus-version review; retain context_only"]
    elif r.get("candidate_id")=="targeted_ff8f499834b104e5":
        rem=["verify source authority/version against official original","confirm rights/page/span","future corpus-version review; retain context_only"]
    elif r.get("candidate_id")=="targeted_b6635396f8904ce3":
        rem=["bind local PDF to official article/catalog","restrict facts to experimental strain/trial; no general overwintering claim","future corpus review"]
    elif r.get("candidate_id") in ("targeted_644cdc14755d80c6","targeted_583c210ee8e8ddfd"):
        rem=["resolve reuse permission and version linkage","split directly supported species-scoped propositions before future admission"]
    elif not cid:
        rem=["discard keyword-only lead unless exact source/document/chunk/page/span is located"]
    else:
        rem=["retain Step3B gate; obtain official original/version and review in a later corpus version"]
    ctx_rows.append({"candidate_id":r.get("candidate_id"),"species":r.get("species"),"category":r.get("category"),
        "claim_candidate":r.get("claim_candidate"),"document_id":r.get("document_id"),"chunk_id":cid,
        "source_document":c.get("source_title") or r.get("source_pdf_path"),
        "corpus_status":{"retrieval_role":role,"benchmark_eligible":c.get("benchmark_eligible",r.get("corpus_benchmark_eligible")),
            "source_verified":c.get("source_verified",r.get("corpus_source_verified"))},
        "original_exclusion_reason":c.get("exclusion_reason") or c.get("eligibility_reason") or c.get("retrieval_exclusion_reason"),
        "exclusion_reason_note":"If null, the frozen row has no dedicated reason field; context_only and benchmark_eligible=false remain the recorded state.",
        "step3b_blocking_reason":r.get("blocking_reason"),"pdf_open":r.get("source_pdf_open"),
        "pdf_sha256":r.get("source_pdf_sha256"),"pdf_checksum_matches_record":r.get("source_sha256_matches_expected"),
        "page":r.get("page"),"support_span_checks":r.get("support_span_text_checks",[]),
        "parser_ocr_quality":{"parser_name":c.get("parser_name"),"extraction_method":c.get("extraction_method"),
            "warnings":c.get("warnings",[]),"extraction_confidence":c.get("extraction_confidence")},
        "source_authenticity":r.get("source_identity_status"),
        "rights_or_reuse":"Manual 17 reuse permission explicitly unresolved" if "技術手冊17" in str(r.get("source_pdf_path")) else "unknown; verify before a new corpus admission",
        "species_applicability":r.get("species"),"required_remediation":rem,"is_context_only":ctx,
        "future_corpus_admission_candidate":bool(ctx and cid and r.get("chunk_exists")),"frozen_eligibility_label_changed":False})
ctx_summary={"frozen_corpus_modified":False,"rows":ctx_rows,
    "context_only_rows":sum(x["is_context_only"] for x in ctx_rows),
    "future_corpus_admission_candidates":[x["candidate_id"] for x in ctx_rows if x["future_corpus_admission_candidate"]]}

# Read-only frozen file hashes.
paths={
"Evaluation_Corpus_v2":"data/evaluation/corpus_v2.jsonl",
"E1_manifest":"reports/evaluation/experiments/E1_grounded_bm25_v1/experiment_manifest.json",
"E1_index_manifest":"data/evaluation/indexes/E1_grounded_bm25_v1/index_manifest.json",
"E2_manifest":"reports/evaluation/experiments/E2_grounded_dense_v1/experiment_manifest.json",
"E2_index_manifest":"data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json",
"E2_vectors":"data/evaluation/indexes/E2_grounded_bge_m3_v1/vectors.f32",
"E2_query_vectors":"data/evaluation/indexes/E2_grounded_bge_m3_v1/query_vectors.f32",
"E4_manifest":"reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/experiment_manifest.json",
"E4_ranking_trace":"reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/ranking_traces.jsonl",
"E4_reranker_trace":"reports/evaluation/experiments/E4_grounded_rrf_reranker_v1/reranker_traces.jsonl",
"rag_store_sqlite3":"rag_store.sqlite3"}
expected={
"Evaluation_Corpus_v2":"540a7dfa641fdbf9c2246feea75a226ade41a8e85d5c995fa5b3c8514aa03162",
"E1_manifest":"5122b6ff5c5b684c1a82df3159524c6985e67e6ca81da8ffdb8c928017ce35b5",
"E1_index_manifest":"8fe631dafe193e71ea1bfc9e2dca0e97209bd317c75536552fcf357ab3316a8b",
"E2_manifest":"c07d1c218ab0d3798886db59586aa3e1dd8e6cf83e10a0b65fea2b2dbb3b131f",
"E2_index_manifest":"ecf4b2428f229bb32591a4bb66bc0859ff34ee05838e9560480e90db01fe900b",
"E2_vectors":"7607c0cbde53c18b80aa4972c4f62d181e8d4596a049c0bd474cfe41db87abc2",
"E2_query_vectors":"f6bb5a4f2ae8f9a73e18ba2f133809288cf2e4fe1f6a0fb23f41706370d1f359",
"E4_manifest":"80236c7346ac9a4a527fd2fcc596fce951366a169170ac262dabfd4741d56ea6",
"E4_ranking_trace":"9f5285ab64552f98b3b90acdba9ff19cc01c9e1bccb9eb935f145790c265ec9d",
"E4_reranker_trace":"a21d830f1886333aa1ddb284264a9306bfde8282eb69a23fd84277a1994f2a57",
"rag_store_sqlite3":"d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"}
anchors=[]
for name,rel in paths.items():
    p=ROOT/rel; actual=fsha(p); st=p.stat()
    anchors.append({"name":name,"path":rel,"expected_sha256":expected[name],"actual_sha256":actual,
        "match":actual==expected[name],"size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns})
assert all(x["match"] for x in anchors)
model_digests={
"deepseek-r1:7b":"755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f",
"qwen2.5-coder:7b":"dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364",
"hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M":"aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42",
"gemma2:9b":"ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b",
"mistral-nemo:12b-instruct-2407-q4_K_M":"daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55"}
sqlite=next(x for x in anchors if x["name"]=="rag_store_sqlite3")
compat={"checked_at_utc":STAMP,"production_app_modified":False,"production_http_smoke":"not_tested",
"sqlite":{**sqlite,"read_only":True,"quick_check":"not repeated this step; Step3B last recorded quick_check=ok"},
"current_frozen_anchor_rechecks":anchors,
"ollama_tags_GET_read_only_this_run":{"success":True,"endpoint":"http://127.0.0.1:11434/api/tags","digests":model_digests},
"phase15_20_protected_files":{"last_comprehensive_check":"Step3B compatibility report","count":636,"mismatches":0,
"this_step":"No protected directory writes; current corpus/index/E4/database anchors and Ollama digests rechecked."},
"phase20_1_protected_reports":{"last_comprehensive_check":"Step3B compatibility report","count":35,"mismatches":0,
"this_step":"Earlier reports read-only; new outputs isolated in Step3C."},
"source_additions":0,"formal_source_admissions":0,"corpus_rebuilds":0,"e4_rebuilds":0,
"benchmark_questions_created":0,"model_scoring_requests":0,"winner":None}

screen_total=sum(oldc.values())+sum(newc.values())
assert screen_total==11
write_json("execution_manifest.json",{"phase":"RAG v2 Phase 20.1E Exec r3 Step 3C","execution_id":"phase20_1E_exec_r3_step3c",
"checked_at_utc":STAMP,"workdir":str(ROOT),"report_dir":str(OUT),
"scope":["eligible existing-corpus evidence expansion","context-only audit","official-source acquisition handoff","pytest tempfile isolation diagnostics"],
"candidate_cap":48,"fresh_candidates_reviewed":34,"prior_overlap_excluded":[excluded_overlap],
"source_additions":0,"formal_source_admissions":0,"corpus_rebuilds":0,"e4_rebuilds":0,
"benchmark_questions_created":0,"model_scoring_requests":0,"winner":None,"historical_reports_overwritten":False})
write_json("candidate_overlap_audit.json",{"needs_review_pool":317,"step2b_pilot_rows":14,"step3b_review_rows":8,
"candidate_ids_inspected_before_dedup":35,"fresh_candidates_reviewed":34,
"prior_overlap_excluded":[{"candidate_id":excluded_overlap,"reason":"Already assessed in Step2B; excluded from current denominator."}],
"unexpected_overlap_in_fresh_batch":[],"dedup_basis":["original/candidate ID","chunk ID","document ID","source SHA-256","page/source span"],
"count_note":"486 candidate chunks (317 needs_review, 169 rejected) are not Evidence Unit counts."})
write_jsonl("normal_risk_batch_decisions.jsonl",decisions)
write_jsonl("new_silver_units.jsonl",units)
write_json("context_only_eligibility_audit.json",ctx_summary)
write_jsonl("official_source_acquisition_packet.jsonl",packets)
write_json("source_priority_matrix.json",{"pending_official_sources":9,"downloads_this_step":0,
"priority_rule":"Current official law first; multi-species cold hazards; disease sources for empty cells; then applicability-limited research/formula sources.",
"items":packets})
write_json("medication_law_remaining_gaps.json",{"baseline_verified_ready":law0.get("verified_ready_units",0),
"verified_ready_this_step":0,"target":law0.get("target_units",30),
"current_official_parent_source":law0.get("current_official_parent_source"),"article_3_effect":law0.get("article_3_effect"),
"local_attachment":law0.get("local_attachment"),"attachment_bytes_match_current_online_version":law0.get("current_attachment_version_matched_to_online_bytes"),
"item_level_effective_status":law0.get("current_effective_status_of_specific_annex_entry"),
"species_specific_scope":law0.get("species_specific_scope"),
"remaining_species_gaps":[{"species":sp,"verified_units":0,"requirements":["current official attachment bytes/hash","exact item/provision and effective version","target species and indication/use scope","legal/applicability review"]} for sp in species],
"no_dosage_or_withdrawal_inference":True})
write_json("calculation_remaining_gaps.json",{"candidate_assignment_rows":calc0.get("candidate_chunk_rows_reviewed",72),
"unique_candidate_chunks":s2["candidate_counts"].get("calculation_candidate_unique_chunk_ids"),
"nonempty_formula_cue_rows":calc0.get("nonempty_formula_cue_rows",5),
"distinct_text_cues":calc0.get("distinct_formula_text_cues",2),"verified_formula_count":0,"target":30,
"formula_cues":calc0.get("formula_cues",[]),"blocking_gaps":calc0.get("missing_fields",[]),
"FCR_status":"not_verified; variables, units, range, assumptions, rounding, tolerance and source applicability remain incomplete",
"SGR_status":"four repeated labels, not a complete formula","deterministic_gold_answers_created":0,"LLM_used_for_gold":False})
write_json("benchmark_feasibility_notes.json",{"target_distinct_units_per_cell":5,"species_count":6,"category_count":6,
"cell_count":36,"design_target_units":180,"current_formal_units":screen_total,"current_shortfall":180-screen_total,
"READY_5_PLUS":ready5,"PARTIAL_1_TO_4":partial,"NO_EVIDENCE":empty,
"structurally_infeasible_declared":False,
"note":"No exhaustive targeted source acquisition/admission has happened; do not declare structural infeasibility or revise the five-unit target.",
"future_dependencies":["obtain official originals/version snapshots","complete rights and applicability review","new isolated corpus-version admission if approved","reassess distinct propositions per cell"],
"cells":matrix})
write_json("evidence_matrix_after_step3c.json",{"checked_at_utc":STAMP,"species":species,"categories":categories,"cells":matrix,
"summary":{"cells":36,"READY_5_PLUS":ready5,"PARTIAL_1_TO_4":partial,"NO_EVIDENCE":empty,
 "baseline_ready_units":7,"new_existing_corpus_silver_units":len(units),"total_formal_ready_units":7+len(units),
 "normal_target":120,"normal_shortfall":120-(7+len(units))}})
write_json("readiness_after_step3c.json",{"checked_at_utc":STAMP,"four_models_ready":True,"independent_judge_ready":True,
 "normal_risk_ready_units":7+len(units),"normal_risk_target_units":120,"normal_risk_shortfall":120-(7+len(units)),"normal_evidence_ready":False,
"medication_law_verified_ready_units":0,"medication_law_target_units":30,"high_risk_ready":False,
"calculation_verified_ready_units":0,"calculation_target_units":30,"calculation_ready":False,
"strict_matrix_ready":False,"strict_matrix_cells_at_target":ready5,"strict_matrix_cells_partial":partial,"strict_matrix_cells_empty":empty,
"final_corpus_ready":True,"final_corpus_identity":"immutable Evaluation Corpus v2 alias; no source additions",
"e4_final_ready":True,"e4_final_identity":"historical E4-compatible frozen alias; no rebuild",
"phase20_2_benchmark_construction_ready":False,"source_additions_this_step":0,
"formal_admissions":0,"winner":None})
write_json("compatibility.json",compat)
write_json("test_interpreter_inventory.json",{"checked_at_utc":STAMP,"packages_installed":False,
"interpreters":[
{"path":r"C:\Users\ethan\anaconda3\python.exe","python":"3.14.6","pytest":"9.0.3","python_docx":False,"PyMuPDF":False},
{"path":r"C:\Python314\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"PyMuPDF":False},
{"path":r".venv\Scripts\python.exe","python":"3.14.7","pytest":False,"python_docx":True,"PyMuPDF":True},
{"path":r".venv-ragas\Scripts\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"PyMuPDF":False},
{"path":r".venv-reranker\Scripts\python.exe","python":"3.14.7","pytest":False,"python_docx":False,"PyMuPDF":False}],
"single_interpreter_has_all_three":False,"pytest_probe_interpreter":r"C:\Users\ethan\anaconda3\python.exe",
"pdf_extraction_interpreter":r".venv\Scripts\python.exe"})
write_json("test_tempfile_probe.json",{"prior_full_suite":{"passed":525,"skipped":6,"failed":22,"errors":4,"repo_collection_errors":9},
"full_suite_rerun_this_step":"not_run","temp_overrides":"TEMP/TMP/TMPDIR set only on test child process; no global environment changes.",
"tempfile_gettempdir":str(OUT/"tmp/python_temp"),"dedicated_temp_root":str(OUT/"tmp"),
"python_tempfile":{"TemporaryDirectory_created":True,"gettempdir_selected_dedicated_root":True,"write_read":"failed","cleanup":"failed",
"exception":"PermissionError errno=13 opening probe.txt; cleanup PermissionError WinError 5 in shutil.rmtree",
"example_paths":["tmp/python_temp/phase20_1e_probe_vbn6gj_d/probe.txt","tmp/python_temp/phase20_1e_probe_cdqv2b8n"]},
"pytest_fixture_probe":{"test":"one tmp_path round-trip probe","passed":0,"errors":1,"stage":"fixture setup/cleanup",
"exception":"PermissionError WinError 5: Access denied cleaning explicit basetemp","basetemp":str(OUT/"tmp/pytest_base"),
"warning":"pytest cache provider attempted default repository-root cache path; no cache/ACL setting changed."},
"cleanup":{"result":"Sandbox denied cleanup with access denied","ACL_or_policy_changed":False,
"known_residual_paths":[str(OUT/"tmp/python_temp"),str(OUT/"tmp/pytest_base"),
r"C:\my project\115_marine_project\pytest-cache-files-f67a58ur",r"C:\my project\115_marine_project\pytest-cache-files-mk1_xrtk"],
"note":"Two older root pytest-cache-files directories predated this probe and were not touched; no cleanup retry was attempted."},
"action":"Use an approved cleanable temp root and one interpreter containing pytest, python-docx and PyMuPDF; rerun unchanged failures only after the environment changes."})

def table(head,rows):
    return "\n".join(["| "+" | ".join(head)+" |","|"+"|".join(["---"]*len(head))+"|"]+
        ["| "+" | ".join(str(c).replace("|","\\|") for c in r)+" |" for r in rows])
cell_rows=[(x["species"],x["category"],x["baseline_ready"],x["new_existing_corpus_silver_ready"],x["total_formal_ready"],x["remaining_shortfall"],x["status"]) for x in matrix]
source_rows_md=[(x["priority"],x["source_id"],x["official_title"],x["status"]) for x in packets]
summary=f"""# Phase 20.1E Exec r3 — Step 3C Summary

- Fresh candidates deeply reviewed: {len(decisions)} of 317 needs_review candidates (maximum allowed: 48; the cap is not a target).
- One previous overlap was excluded: {excluded_overlap}.
- Decision counts: {outcome_counts['silver_ready']} candidate rows passed, {outcome_counts['needs_review']} remain needs_review, {outcome_counts['rejected']} rejected.
- New distinct Corpus-Grounded Silver units: {len(units)}; human_reviewed=false for all.
- Five additional propositions have local PDF hash/page matches but remain needs_review because the frozen corpus has source_verified=false and ingestion_status=accepted_with_warning.
- Total formal existing Silver: {7+len(units)}/120; shortfall {120-(7+len(units))}.
- Matrix: {ready5} cell at target, {partial} partial, {empty} with no ready evidence.
- Medication/Law verified: 0/30. Calculation verified: 0/30.
- Nine official sources are in the manual acquisition packet; downloads/admissions: 0.
- Frozen corpus, E1/E2, Historical E4, model digests and SQLite anchors matched. Production HTTP smoke: not_tested.
- Tempfile and pytest tmp_path probes failed with Sandbox PermissionError/WinError 5. Full suite not rerun; no dependencies, ACL, policy or assertions changed.
- Corpus/E4 rebuilds: 0; benchmark questions: 0; model scoring: 0; Winner: null.

## Evidence counts by cell

{table(["Species","Category","Baseline","New","Total","Shortfall","Status"],cell_rows)}

## Official-source acquisition priority

{table(["Priority","Source ID","Official title","Status"],source_rows_md)}

## Test blocker

The child process selected the isolated Step3C tempfile root after TEMP/TMP/TMPDIR overrides, but TemporaryDirectory write/cleanup failed with PermissionError (errno 13 / WinError 5). The single pytest tmp_path probe errored in fixture setup/cleanup under the explicit basetemp. The full suite was not rerun. Sandbox denied cleanup of known probe-created temp/cache directories; see test_tempfile_probe.json. No ACL or policy change was made.

## Readiness

normal_evidence_ready=false; high_risk_ready=false; calculation_ready=false; strict_matrix_ready=false; phase20_2_benchmark_construction_ready=false. No structural infeasibility is declared because targeted source acquisition/admission remains incomplete.
"""
with (OUT/"step3c_summary.md").open("w",encoding="utf-8",newline="\n") as f:
    f.write(summary)

print(json.dumps({"report_dir":str(OUT),"fresh_reviewed":len(decisions),"outcomes":dict(outcome_counts),
    "new_silver_units":len(units),"matrix":{"ready5":ready5,"partial":partial,"empty":empty},
    "pending_sources":len(packets),"frozen_anchors_matched":sum(x["match"] for x in anchors),
    "files":sorted(p.name for p in OUT.iterdir() if p.is_file())},ensure_ascii=False,indent=2))
