import json, hashlib, pathlib, random, re, itertools, sys, datetime, os
from collections import Counter, defaultdict

ROOT = pathlib.Path(r"C:\my project\115_marine_project")
OUT = ROOT / r"reports/evaluation/fish_test_phase_n_20261016_205314"
M = ROOT / r"reports/evaluation/fish_test_phase_m_20261016_195819"
RUN = ROOT / r"reports/evaluation/fish_test_run_20261012_152244"
G = ROOT / r"reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009"
PHASES = {
    "I": ROOT / r"reports/evaluation/fish_test_phase_i_20261014_195032",
    "J": ROOT / r"reports/evaluation/fish_test_phase_j_20261015_190617",
    "K": ROOT / r"reports/evaluation/fish_test_phase_k_20261016_181425",
    "L": ROOT / r"reports/evaluation/fish_test_phase_l_20261016_190457",
    "M": M,
}
SEED = 20261016
SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
CATEGORIES = ["Fact", "Water Quality", "Disease", "Climate / Cold", "Medication / Law", "Calculation"]

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_jsonl(path):
    if not path.exists(): return []
    rows=[]
    for n,line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(),1):
        if not line.strip(): continue
        try: rows.append(json.loads(line))
        except Exception as e: raise ValueError(f"Invalid JSONL {path}:{n}: {e}")
    return rows

def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")

def sha_text(s): return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

questions = read_jsonl(RUN / "fish_test_questions_normalized.jsonl")
trace = read_jsonl(RUN / "retrieval_trace.jsonl")
assert len(questions)==180, f"questions={len(questions)}"
assert len(trace)==180, f"retrieval={len(trace)}"
qmap={x["question_id"]:x for x in questions}
tmap={x["question_id"]:x for x in trace}

# Index immutable corpus metadata by chunk ID for source identity fields.
corpus_path=ROOT / "data/evaluation/corpus_v2.jsonl"
corpus_by_chunk={}
for row in read_jsonl(corpus_path):
    cid=row.get("chunk_id")
    if cid: corpus_by_chunk[cid]=row

# Collect only annotation/pilot records from Phases I-M; these are the rule-tuning exposure set.
qid_re=re.compile(r"FT-(?:milkfish|tilapia|grouper|seabass|mullet|eel)-Q\d{2}",re.I)
used_qids=set()
exposure_files=[]
include_tokens=("pilot","sample","development","holdout","validation","human_review_sampling","question_selection","judge_call_archive")
exclude_tokens=("summary","comparison","report","manifest","compatibility","validation_report","output_validation")
for phase,folder in PHASES.items():
    if not folder.exists(): continue
    for p in folder.iterdir():
        if not p.is_file(): continue
        low=p.name.lower()
        if not low.endswith((".jsonl",".json")): continue
        if not any(t in low for t in include_tokens): continue
        if any(t in low for t in exclude_tokens) and "sample" not in low: continue
        try: text=p.read_text(encoding="utf-8-sig",errors="ignore")
        except Exception: continue
        found=set(qid_re.findall(text))
        if found:
            used_qids.update(q.upper() for q in found)
            exposure_files.append({"phase":phase,"file":str(p.relative_to(ROOT)),"question_ids_found":len(found)})
# Also read frozen selection manifests whose filenames do not contain pilot.
for p in [PHASES["M"]/"independent_validation_sample_frozen.json", PHASES["I"]/"pilot_question_selection.json"]:
    if p.exists():
        try:
            obj=read_json(p)
            found=set(qid_re.findall(json.dumps(obj,ensure_ascii=False)))
            used_qids.update(q.upper() for q in found)
            exposure_files.append({"phase":"manifest","file":str(p.relative_to(ROOT)),"question_ids_found":len(found)})
        except Exception: pass

def species_of(q):
    s=q.get("species_chinese") or q.get("species_label_in_test_data") or ""
    for name in SPECIES:
        if name in s: return name
    # ID fallback, used only for strata identity
    idv=q.get("question_id","")
    mapid={"milkfish":"虱目魚","tilapia":"吳郭魚","grouper":"石斑魚","seabass":"鱸魚","mullet":"烏魚","eel":"鰻魚"}
    m=re.match(r"FT-([^-]+)-",idv)
    return mapid.get(m.group(1),"未知")

def category_of(q):
    c=q.get("inferred_category") or q.get("category") or "Unclassified"
    aliases={"Climate":"Climate / Cold","Climate/Cold":"Climate / Cold","Medication/Law":"Medication / Law","Medication / Law":"Medication / Law"}
    return aliases.get(c,c)

eligible=defaultdict(list)
for q in questions:
    qid=q["question_id"].upper()
    sp=species_of(q)
    if sp not in SPECIES or qid in used_qids: continue
    eligible[sp].append(q)

rng=random.Random(SEED)
# Pick two QIDs per species with distinct categories where possible, maximizing total category coverage.
species_options={}
for sp in SPECIES:
    candidates=list(eligible[sp])
    rng.shuffle(candidates)
    pairs=[]
    for a,b in itertools.combinations(candidates,2):
        ca,cb=category_of(a),category_of(b)
        diversity=int(ca!=cb)
        tie=rng.random()
        pairs.append((diversity,tie,a,b))
    pairs.sort(key=lambda z:(-z[0],z[1]))
    species_options[sp]=pairs

# Dynamic program over category-count vectors. It first maximizes distinct
# categories, then seeks balanced representation (target two per category),
# then prefers two different categories within each species. Ties are seeded.
cat_index={c:i for i,c in enumerate(CATEGORIES)}
pair_options_by_species={}
for sp in SPECIES:
    by_cat=defaultdict(list)
    for q in eligible[sp]: by_cat[category_of(q)].append(q)
    for values in by_cat.values(): rng.shuffle(values)
    opts=[]
    cats=[c for c in CATEGORIES if by_cat.get(c)]
    for ca,cb in itertools.combinations(cats,2):
        opts.append((ca,cb,by_cat[ca][0],by_cat[cb][0],rng.random()))
    if not opts:
        for c in cats:
            if len(by_cat[c])>=2: opts.append((c,c,by_cat[c][0],by_cat[c][1],rng.random()))
    rng.shuffle(opts)
    pair_options_by_species[sp]=opts
dp={(tuple([0]*len(CATEGORIES)),0):(0.0,[])}
for sp in SPECIES:
    nd={}
    for (counts,diversity),(tie,chosen) in dp.items():
        for ca,cb,a,b,opt_tie in pair_options_by_species[sp]:
            new=list(counts); new[cat_index[ca]]+=1; new[cat_index[cb]]+=1
            nkey=(tuple(new),diversity+int(ca!=cb))
            cvalue=(tie+opt_tie,chosen+[(sp,a,b,ca,cb)])
            old=nd.get(nkey)
            if old is None or cvalue[0]<old[0]: nd[nkey]=cvalue
    dp=nd
best_key,best=max(dp.items(),key=lambda kv:(sum(c>0 for c in kv[0][0]),-sum((c-2)**2 for c in kv[0][0]),kv[0][1],-kv[1][0]))
selected=[]
for sp,a,b,ca,cb in best[1]: selected.extend([a,b])
assert len(selected)==12 and all(sum(species_of(q)==sp for q in selected)==2 for sp in SPECIES)
selected_ids=[q["question_id"] for q in selected]
assert not(set(x.upper() for x in selected_ids)&used_qids), "selected question appeared in prior Phase I-M pilots"

# Build source lookup from frozen Corpus v2 records and retrieval trace.
selected_contexts=[]
sample_records=[]
for q in selected:
    qid=q["question_id"]
    tr=tmap[qid]
    contexts=sorted(tr.get("contexts",[]),key=lambda x:x.get("top5_rank",x.get("rank",999)))
    if len(contexts)!=5: raise ValueError(f"{qid} has {len(contexts)} contexts, expected 5")
    qctx=[]
    for rank,c in enumerate(contexts,1):
        cid=c.get("chunk_id")
        corp=corpus_by_chunk.get(cid,{})
        text=c.get("text","")
        source_title=corp.get("source_title") or corp.get("article") or "not present in corpus metadata"
        source_version=corp.get("source_version") or "not recorded in Corpus v2 metadata"
        record={
            "question_id":qid,"species":species_of(q),"category":category_of(q),"question_text":q.get("question_text",""),
            "rank":rank,"chunk_id":cid,"document_id":c.get("document_id"),
            "source_id":corp.get("source_id","not present in corpus metadata"),
            "source_name":source_title,"source_version":source_version,
            "chunk_version":corp.get("chunk_version"),"source_file_sha256":corp.get("source_checksum"),
            "source_url":corp.get("source_url"),
            "page":c.get("page",corp.get("page_start")),
            "context_text":text,"context_sha256":c.get("text_sha256") or sha_text(text),
            "corpus_version":tr.get("corpus_version"),"corpus_sha256":tr.get("corpus_sha256"),
            "index_checksum":tr.get("index_checksum"),
            "human_label":None,"human_support_reason":None,"reviewer":None,"review_date":None,
            "human_status":"PENDING_HUMAN_REVIEW"
        }
        qctx.append(record); selected_contexts.append(record)
    sample_records.append({
        "question_id":qid,"species":species_of(q),"category":category_of(q),
        "question_text":q.get("question_text",""),"candidate_reference_answer":q.get("candidate_reference_answer"),
        "source_records":q.get("source_records",[]),"question_sha256":sha_text(q.get("question_text","")),
        "context_count":len(qctx),"context_sha256s":[x["context_sha256"] for x in qctx]
    })
assert len(selected_contexts)==60

# Freeze the sample with source/context hashes; manifest intentionally contains no P@5 outcomes.
freeze_core={
    "selection_id":"phase_n_human_context_pilot_v1",
    "status":"FROZEN_BEFORE_HUMAN_ANNOTATION",
    "seed":SEED,
    "selection_method":"deterministic stratified randomized selection; 2 per species; maximize six-category coverage; no P@5/AI output used",
    "excluded_prior_tuning_question_ids":sorted(used_qids),
    "selected_question_ids":selected_ids,
    "species_counts":dict(Counter(species_of(q) for q in selected)),
    "category_counts":dict(Counter(category_of(q) for q in selected)),
    "selected_contexts":[{"question_id":x["question_id"],"rank":x["rank"],"chunk_id":x["chunk_id"],"context_sha256":x["context_sha256"],"source_id":x["source_id"],"source_version":x["source_version"]} for x in selected_contexts]
}
freeze_hash=sha_text(json.dumps(freeze_core,ensure_ascii=False,sort_keys=True,separators=(",",":")))
freeze_core["manifest_sha256"]=freeze_hash
write_json(OUT/"sample_selection_manifest.json",freeze_core)
write_jsonl(OUT/"pilot_12_questions_frozen.jsonl",sample_records)
write_jsonl(OUT/"pilot_60_contexts_frozen.jsonl",selected_contexts)

# Audit historical 28 Relevant rows; keep historical labels unchanged and classify suspected issue only.
m_audit=read_jsonl(M/"phase_m_relevance_content_support_audit.jsonl")
m_rows=read_jsonl(M/"pilot_50_development_results.jsonl")+read_jsonl(M/"pilot_50_holdout_results.jsonl")
m_by_key={(x.get("question_id"),x.get("chunk_id"),int(x.get("rank",0))):x for x in m_rows}
candidate_by_id=qmap
def required_elements(q):
    parts=[]
    for k,label in [("candidate_reference_answer","Candidate answer"),("candidate_scoring_key_points","Candidate scoring points"),("candidate_correct_option","Candidate correct option")]:
        v=q.get(k)
        if v not in (None,"",[],{}): parts.append(f"{label}: {v}")
    return " | ".join(parts) if parts else "Candidate answer elements unavailable; human reviewer should derive from question."
def issue_for(a, ctx, q):
    audit=a.get("retrospective_content_audit","")
    if audit=="PARTIAL_SUPPORT_REVIEW":
        return "VALID_PARTIAL_SUPPORT"
    if audit=="NO_OBVIOUS_CONTENT_MISMATCH":
        return "DIRECT_ANSWER_SUPPORT"
    question=(a.get("question_text") or "").lower()
    text=(ctx.get("chunk_text") or "").lower()
    # Check Corpus-declared species scope before classifying topic or numeric gaps.
    sp=species_of(q)
    corp=corpus_by_chunk.get(a.get("chunk_id"),{})
    doc_species=corp.get("species") or ""
    if isinstance(doc_species,list): doc_species=" ".join(doc_species)
    if any(s in str(doc_species) for s in SPECIES) and sp not in str(doc_species):
        return "SPECIES_MISMATCH"
    if any(token in question for token in ["第一年","第二年","第1年","第2年","轉養","抱卵","停電","寒流","條件","情境","是否","何時"]):
        return "MISSING_REQUIRED_CONDITION"
    numeric_request=bool(re.search(r"\d|°c|範圍|數值|幾|多少|最接近|單位|每公頃|ppt",question))
    if numeric_request:
        return "MISSING_REQUIRED_VALUE"
    # If the original judge's own reason says not answer the question.
    reasons=(a.get("round1_reason","")+" "+a.get("round2_reason","")).lower()
    if any(t in reasons for t in ["does not directly address","does not answer","not address","unrelated","different topic"]):
        return "TOPIC_ONLY_MATCH"
    return "INSUFFICIENT_EVIDENCE"

false_rows=[]
for a in m_audit:
    key=(a.get("question_id"),a.get("chunk_id"),int(a.get("rank",0)))
    ctx=m_by_key.get(key,{})
    q=qmap.get(a.get("question_id"),{})
    typ=issue_for(a,ctx,q)
    content=ctx.get("chunk_text","")
    quote=a.get("exact_quote")
    false_rows.append({
        "question_id":a.get("question_id"),"species":ctx.get("species") or species_of(q),
        "category":ctx.get("category") or category_of(q),"question_text":a.get("question_text"),
        "required_answer_elements":required_elements(q),"rank":a.get("rank"),"chunk_id":a.get("chunk_id"),
        "source_name":ctx.get("source_title"),"source_version":ctx.get("source_version"),
        "original_chunk_text":content,"exact_evidence_span":quote,
        "historical_ai_label":a.get("final_label_original"),
        "ai_round1_reason":a.get("round1_reason"),"ai_round2_reason":a.get("round2_reason"),
        "phase_m_content_audit":a.get("retrospective_content_audit"),
        "suspected_issue_type":typ,"audit_reason":a.get("audit_reason"),
        "historical_label_modified":False,"annotation_status":"AI_RETROSPECTIVE_WARNING_NOT_HUMAN_GOLD"
    })
write_jsonl(OUT/"phase_m_false_relevant_analysis.jsonl",false_rows)

# Enrich the 63 human review items with the preserved Phase M record; never fill human judgement fields.
review_list=read_jsonl(M/"human_review_sampling_list.jsonl")
audit_by_key={(x.get("question_id"),x.get("chunk_id"),int(x.get("rank",0))):x for x in m_audit}
review_rows=[]
for r in review_list:
    key=(r.get("question_id"),r.get("chunk_id"),int(r.get("rank",0)))
    ctx=m_by_key.get(key,{})
    aud=audit_by_key.get(key,{})
    q=qmap.get(r.get("question_id"),{})
    quote=aud.get("exact_quote")
    if not quote:
        for round_name in ("round_1","round_2"):
            rr=ctx.get(round_name) or {}
            cits=rr.get("citation")
            if isinstance(cits,list) and cits:
                quote=cits[0].get("quote")
                break
            if isinstance(cits,dict): quote=cits.get("quote")
    review_rows.append({
        "Question ID":r.get("question_id"),"Species":r.get("species"),"Category":r.get("category"),
        "Original Question":q.get("question_text") or ctx.get("question_text"),
        "Required Answer Elements":required_elements(q),
        "Rank":r.get("rank"),"Chunk ID":r.get("chunk_id"),
        "Source Name":ctx.get("source_title") or "not present in preserved Phase M record",
        "Source Version":ctx.get("source_version") or "not present in preserved Phase M record",
        "Original Chunk Text":ctx.get("chunk_text") or "not present in preserved Phase M record",
        "Exact Evidence Span":quote or "no verified citation span in preserved record",
        "AI Initial Label":r.get("final_label"),
        "Content Audit Warning":aud.get("audit_reason") or r.get("reason_for_human_sampling"),
        "Human Final Label":"",
        "Human Support Reason":"",
        "Reviewer":"",
        "Review Date":"",
        "Human Status":"PENDING_HUMAN_REVIEW",
        "_chunk_sha256":ctx.get("chunk_text_sha256"),
        "_source_sha256":ctx.get("source_file_sha256")
    })
write_jsonl(OUT/"human_review_queue_63.jsonl",review_rows)

# Hidden-from-reviewer AI comparison reference: original Phase G decisions mapped by exact question/chunk/rank.
g_rows=read_jsonl(G/"context_auto_annotations_900.jsonl")
g_by_key={(x.get("question_id"),x.get("chunk_id"),int(x.get("rank",0))):x for x in g_rows}
ai_reference=[]
for x in selected_contexts:
    g=g_by_key.get((x["question_id"],x["chunk_id"],x["rank"]))
    ai_reference.append({
        "question_id":x["question_id"],"chunk_id":x["chunk_id"],"rank":x["rank"],
        "phase_g_ai_label":(g or {}).get("relevance_label"),
        "phase_g_ai_reason":(g or {}).get("relevance_reason"),
        "annotator_model":(g or {}).get("annotator_model"),
        "annotator_digest":(g or {}).get("annotator_digest"),
        "context_sha256":x["context_sha256"],
        "blind_until_human_annotation_locked":True,
        "note":"Analyst-only comparison input; do not expose in the human-facing pilot workbook."
    })
write_jsonl(OUT/"pilot_ai_reference_blinded.jsonl",ai_reference)

# Current human status and metric shells.
write_json(OUT/"human_annotation_status.json",{
    "as_of":"2026-10-16","reviewer_annotations_received":False,
    "human_gold_reviewed":0,"human_review_queue_63":{"total":len(review_rows),"completed":0,"pending":len(review_rows)},
    "independent_pilot":{"questions":12,"contexts":60,"completed_contexts":0,"pending_contexts":60,"selected_species_counts":dict(Counter(species_of(q) for q in selected))},
    "label_options":["1","0","U"],"blank_means":"Pending; never coerce to U or 0",
    "human_final_labels_written_by_agent":0,"status":"WAITING_FOR_HUMAN_REVIEW"
})
write_json(OUT/"context_precision_human_pilot.json",{
    "annotation_method":"HUMAN_VERIFIED_RELEVANCE; no human labels received yet",
    "sample_selection_manifest_sha256":freeze_hash,
    "questions_total":12,"contexts_total":60,"fully_labeled_questions":0,"exact_p5_n":0,
    "exact_p5_mean":None,"per_species":{s:{"questions":2,"exact_p5_n":0,"mean":None} for s in SPECIES},
    "label_counts":{"RELEVANT":0,"IRRELEVANT":0,"UNCERTAIN":0,"PENDING":60},
    "uncertain_bounds_available":False,"status":"PENDING_HUMAN_REVIEW",
    "rule":"P@5=Relevant_Count/5 only when all five labels are 0/1."
})
write_json(OUT/"ai_vs_human_relevance_comparison.json",{
    "status":"PENDING_HUMAN_LABELS","human_n":0,"comparable_binary_n":0,
    "accuracy":None,"precision":None,"recall":None,"false_positive":None,"false_negative":None,
    "confusion_matrix":None,
    "ai_reference_file":"pilot_ai_reference_blinded.jsonl",
    "ai_reference_source":"Phase G original context-level AI annotations keyed by exact QID/chunk/rank; held blind from reviewers",
    "caution":"The 63-row high-risk queue is purposive and must not be used as a population reliability estimate."
})

# Recalculate prior protected 636 hashes using the Phase L frozen path/checksum inventory, read-only.
frozen_path=PHASES["L"]/"frozen_baseline_636_recheck.jsonl"
baseline_rows=read_jsonl(frozen_path)
baseline_results=[]
for r in baseline_rows:
    rel=pathlib.Path(r["path"])
    full=rel if rel.is_absolute() else ROOT/rel
    status="missing"
    actual=None
    try:
        h=hashlib.sha256()
        with full.open("rb") as f:
            for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
        actual=h.hexdigest()
        status="unchanged" if actual==r.get("expected_sha256") else "mismatch"
    except Exception as e:
        status="unreadable"; rerr=str(e)
    baseline_results.append({"path":r["path"],"expected_sha256":r.get("expected_sha256"),"actual_sha256":actual,"status":status,"error":locals().get("rerr")})
    if "rerr" in locals(): del rerr
counts=Counter(x["status"] for x in baseline_results)
sqlite_path=ROOT/"rag_store.sqlite3"
sqlite_hash=None
if sqlite_path.exists():
    h=hashlib.sha256()
    with sqlite_path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    sqlite_hash=h.hexdigest()
write_jsonl(OUT/"frozen_baseline_636_recheck.jsonl",baseline_results)
write_json(OUT/"frozen_baseline_recheck.json",{
    "manifest_source":str(frozen_path.relative_to(ROOT)),"expected_entries":len(baseline_rows),
    "unchanged":counts.get("unchanged",0),"mismatched":counts.get("mismatch",0),
    "missing_or_unreadable":counts.get("missing",0)+counts.get("unreadable",0),
    "all_636_unchanged":len(baseline_rows)==636 and counts.get("unchanged")==636,
    "sqlite_sha256":sqlite_hash,
    "sqlite_expected_sha256":"d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
    "sqlite_matches_expected":sqlite_hash=="d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087",
    "current_run_writes_confined_to":str(OUT.relative_to(ROOT)),
    "note":"Rehashed the frozen Phase L 636-file inventory; no protected files intentionally written."
})

# Persist compact analysis payload for workbook authoring.
question_payload=[]
for q in selected:
    question_payload.append({
        "question_id":q["question_id"],"species":species_of(q),"category":category_of(q),
        "question_text":q.get("question_text",""),"question_sha256":sha_text(q.get("question_text","")),
        "candidate_reference_answer":q.get("candidate_reference_answer"),
        "candidate_scoring_key_points":q.get("candidate_scoring_key_points"),
        "contexts":[x for x in selected_contexts if x["question_id"]==q["question_id"]]
    })
write_json(OUT/"workbook_payload.json",{"review63":review_rows,"pilot12":question_payload,"manifest_sha256":freeze_hash})

# Verify output consistency.
assert len(false_rows)==len(m_audit)==28
assert len(review_rows)==len(review_list)==63
assert len(selected_contexts)==60
assert all(x["Human Final Label"]=="" and x["Human Status"]=="PENDING_HUMAN_REVIEW" for x in review_rows)
assert all(x["human_label"] is None and x["human_status"]=="PENDING_HUMAN_REVIEW" for x in selected_contexts)
# File digest for key source trace artifacts
audit={
 "phase_m_relevant_audit_rows":len(m_audit),
 "phase_m_review_queue_rows":len(review_list),
 "selected_questions":len(selected),
 "selected_contexts":len(selected_contexts),
 "selected_by_species":dict(Counter(species_of(q) for q in selected)),
 "selected_by_category":dict(Counter(category_of(q) for q in selected)),
 "prior_tuning_qid_count":len(used_qids),
 "prior_tuning_files_scanned":exposure_files,
 "manifest_sha256":freeze_hash,
 "all_contexts_have_text":all(bool(x["context_text"]) for x in selected_contexts),
 "all_selected_qids_excluded_from_prior_pilots":not bool(set(x.upper() for x in selected_ids)&used_qids),
 "all_human_fields_pending":True,
 "phase_m_issue_counts":dict(Counter(x["suspected_issue_type"] for x in false_rows)),
 "phase_m_retrospective_warning_counts":dict(Counter(x["phase_m_content_audit"] for x in false_rows)),
 "frozen_baseline_counts":dict(counts),
 "frozen_636_unchanged":counts.get("unchanged")==636 and len(baseline_rows)==636,
 "sqlite_sha256":sqlite_hash
}
write_json(OUT/"phase_n_preparation_validation.json",audit)
print(json.dumps(audit,ensure_ascii=False,indent=2))


