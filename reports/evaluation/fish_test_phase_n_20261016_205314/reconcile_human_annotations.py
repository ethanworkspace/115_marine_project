import argparse,json,pathlib,hashlib,collections,sys

def load_jsonl(p):
    rows=[]
    for n,line in enumerate(pathlib.Path(p).read_text(encoding="utf-8-sig").splitlines(),1):
        if line.strip(): rows.append(json.loads(line))
    return rows

def write_json(p,obj):
    pathlib.Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(description="Validate completed Phase N human annotations and reconcile P@5/AI comparison.")
    ap.add_argument("--labels-jsonl",required=True,help="Reviewer-exported JSONL; one record per selected QID/chunk/rank.")
    ap.add_argument("--output",required=True,help="New path for reconciliation JSON.")
    ap.add_argument("--phase-dir",default=str(pathlib.Path(__file__).parent))
    a=ap.parse_args()
    base=pathlib.Path(a.phase_dir)
    expected=load_jsonl(base/"pilot_60_contexts_frozen.jsonl")
    ai=load_jsonl(base/"pilot_ai_reference_blinded.jsonl")
    expected_map={(r["question_id"],r["chunk_id"],int(r["rank"])):r for r in expected}
    ai_map={(r["question_id"],r["chunk_id"],int(r["rank"])):r for r in ai}
    inputs=load_jsonl(a.labels_jsonl)
    errors=[]; seen={}; accepted={}
    allowed={"1","0","U"}
    for i,r in enumerate(inputs,1):
        key=(r.get("question_id"),r.get("chunk_id"),int(r.get("rank",-1)))
        if key not in expected_map:
            errors.append({"line":i,"key":key,"error":"record_not_in_frozen_sample"})
            continue
        if key in seen:
            errors.append({"line":i,"key":key,"error":"duplicate_human_annotation"})
            continue
        seen[key]=r
        frozen=expected_map[key]
        if r.get("context_sha256") and r["context_sha256"]!=frozen.get("context_sha256"):
            errors.append({"line":i,"key":key,"error":"context_checksum_mismatch"})
            continue
        raw_label=r.get("human_label")
        label="" if raw_label is None else str(raw_label).strip().upper()
        if not label:
            continue
        if label not in allowed:
            errors.append({"line":i,"key":key,"error":"invalid_label","value":label})
            continue
        if not r.get("reviewer"):
            errors.append({"line":i,"key":key,"error":"reviewer_required"})
            continue
        if not r.get("review_date"):
            errors.append({"line":i,"key":key,"error":"review_date_required"})
            continue
        if not str(r.get("human_support_reason","")).strip():
            errors.append({"line":i,"key":key,"error":"support_reason_required"})
            continue
        accepted[key]={**r,"human_label":label,"human_status":"HUMAN_REVIEWED"}
    qmap=collections.defaultdict(list)
    for key,r in accepted.items(): qmap[key[0]].append(r)
    qresults=[]
    for qid in dict.fromkeys(r["question_id"] for r in expected):
        records=[qmap[qid][i] for i in range(len(qmap[qid]))] if qid in qmap else []
        labels=[str(x.get("human_label","")).upper() for x in records]
        binary=all(x in {"1","0"} for x in labels) and len(records)==5
        rel=labels.count("1"); u=labels.count("U")
        qresults.append({"question_id":qid,"human_contexts_completed":len(records),"relevant":rel,"irrelevant":labels.count("0"),"uncertain":u,
                         "p_at_5":rel/5 if binary else None,"p5_status":"valid" if binary else "pending_or_uncertain"})
    binary_pairs=[]
    for key,h in accepted.items():
        ar=ai_map.get(key,{})
        hl=str(h.get("human_label","")).upper()
        al=str(ar.get("phase_g_ai_label","")).upper()
        al={"RELEVANT":"1","IRRELEVANT":"0","1":"1","0":"0","U":"U"}.get(al,al)
        if hl in {"1","0"} and al in {"1","0"}:
            binary_pairs.append((hl,al))
    tp=sum(h=="1" and x=="1" for h,x in binary_pairs)
    tn=sum(h=="0" and x=="0" for h,x in binary_pairs)
    fp=sum(h=="0" and x=="1" for h,x in binary_pairs)
    fn=sum(h=="1" and x=="0" for h,x in binary_pairs)
    total=len(binary_pairs)
    comparison={"binary_comparable_n":total,"accuracy":(tp+tn)/total if total else None,
                "precision":tp/(tp+fp) if tp+fp else None,"recall":tp/(tp+fn) if tp+fn else None,
                "false_positive":fp,"false_negative":fn,"true_positive":tp,"true_negative":tn}
    complete=sum(x["p5_status"]=="valid" for x in qresults)
    labels_count=collections.Counter(str(x.get("human_label","")).upper() for x in accepted.values())
    result={"phase":"N","frozen_sample_manifest":"sample_selection_manifest.json",
        "expected_contexts":len(expected),"input_rows":len(inputs),"unique_expected_contexts_seen":len(seen),
        "accepted_human_labels":len(accepted),"pending_contexts":len(expected)-len(accepted),
        "validation_errors":errors,"label_counts":{"1":labels_count["1"],"0":labels_count["0"],"U":labels_count["U"]},
        "questions":qresults,"exact_p5_n":complete,"exact_p5_mean":(sum(x["p_at_5"] for x in qresults if x["p_at_5"] is not None)/complete if complete else None),
        "ai_vs_human_binary_comparison":comparison,
        "human_annotation_records_reviewed":len(accepted),"human_gold_reviewed":False,"not_human_gold":True,
        "caution":"This is a 12-question stratified pilot, not an estimate for all 180 questions; binary AI metrics exclude AI or human U labels.",
        "status":"VALIDATED_WITH_PENDING" if not errors else "REVIEW_ERRORS"}
    write_json(a.output,result)
    print(json.dumps({"status":result["status"],"accepted":len(accepted),"pending":len(expected)-len(accepted),"errors":len(errors),"exact_p5_n":complete,"ai_binary_n":total},ensure_ascii=False))
if __name__=="__main__": main()


