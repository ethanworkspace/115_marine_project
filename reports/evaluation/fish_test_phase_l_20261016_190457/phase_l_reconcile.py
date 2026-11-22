from __future__ import annotations
import collections, datetime as dt, importlib.util, json, pathlib, sys

OUT = pathlib.Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))
spec = importlib.util.spec_from_file_location("phase_l_runner_reconciled", OUT / "phase_l_runner.py")
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

def rj(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def rjl(p): return [json.loads(x) for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
def wj(p, x): p.write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def wjl(p, xs):
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for x in xs: f.write(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n")

def source_rows():
    return {(x["question_id"], x["chunk_id"], int(x["rank"])): x for x in r.load_fixed_50()}

def check_round(raw, src):
    out = {"raw_status": raw.get("status"), "raw_label": (raw.get("stage1_parsed") or {}).get("relevance_label"),
           "raw_species_applicability": (raw.get("stage1_parsed") or {}).get("species_applicability"),
           "raw_reason": (raw.get("stage1_parsed") or {}).get("reason"), "validated_label": None,
           "validated_status": "ANNOTATION_ERROR", "scope_guard_v2": None, "exact_span_valid": False,
           "judge_label_scope_conflict": False, "explicit_species_mismatch": False, "review_reasons": []}
    if raw.get("status") != "VALID" or not raw.get("stage1_completed"):
        out["validated_status"] = "INCOMPLETE" if raw.get("status") in {"INCOMPLETE", None} else "ANNOTATION_ERROR"
        out["review_reasons"].append(raw.get("annotation_error") or raw.get("status") or "missing_stage1")
        return out
    parsed = raw.get("stage1_parsed") or {}; label = parsed.get("relevance_label")
    if label not in {"RELEVANT", "IRRELEVANT", "UNCERTAIN"}:
        out["review_reasons"].append("invalid_relevance_label"); return out
    page = r.load_source_page({"document_file_path": src.get("document_file_path"), "page": src.get("page"),
                               "source_title": src.get("source_title"), "document_species": src.get("document_species") or []})
    scope = r.assess_species_scope({"question_species": src.get("question_species"), "question_text": src.get("question_text"),
                                    "chunk_text": src.get("chunk_text") or "", "source_title": src.get("source_title") or "",
                                    "document_species": src.get("document_species") or []}, page)
    out["scope_guard_v2"] = scope
    chunk = src.get("chunk_text") or ""; spans = raw.get("accepted_evidence_spans") or []
    out["exact_span_valid"] = bool(spans) and all(
        isinstance(s.get("start"), int) and isinstance(s.get("end"), int) and 0 <= s["start"] < s["end"] <= len(chunk)
        and chunk[s["start"]:s["end"]] == s.get("quote") and s.get("quote_verified_exact") is True
        and s.get("chunk_sha256") == r.sha256_bytes(chunk.encode("utf-8")) for s in spans)
    out["judge_label_scope_conflict"] = label == "RELEVANT" and parsed.get("species_applicability") == "not_applicable"
    out["explicit_species_mismatch"] = label == "RELEVANT" and scope["status"] == "MISMATCH"
    if label == "IRRELEVANT":
        out.update(validated_label="IRRELEVANT", validated_status="VALID"); return out
    if label == "UNCERTAIN":
        out.update(validated_label="UNCERTAIN", validated_status="VALID_UNCERTAIN")
        out["review_reasons"].append(parsed.get("reason") or "Judge returned UNCERTAIN"); return out
    if scope["status"] == "MISMATCH":
        out.update(validated_label="IRRELEVANT", validated_status="VALID")
        out["review_reasons"].append("source_scope_mismatch_override"); return out
    if label == "RELEVANT" and not out["exact_span_valid"]:
        out["review_reasons"].append("relevant_without_verified_exact_span"); return out
    if scope["status"] == "UNCERTAIN":
        out.update(validated_label="UNCERTAIN", validated_status="VALID_UNCERTAIN")
        out["review_reasons"].append("source_scope_not_established_for_exact_chunk"); return out
    if parsed.get("species_applicability") != "applicable":
        out.update(validated_label="UNCERTAIN", validated_status="VALID_UNCERTAIN")
        out["review_reasons"].append("Judge_relevance_and_species_applicability_conflict"); return out
    out.update(validated_label="RELEVANT", validated_status="VALID")
    return out

def reconcile(file, dest, srcmap):
    rows = rjl(OUT / file); result = []
    for row in rows:
        src = srcmap.get((row["question_id"], row["chunk_id"], int(row["rank"])))
        if not src:
            row["validated_pair_status"] = "INCOMPLETE"; row["validated_final_label"] = None
            row["reconciliation_error"] = "source mapping missing"; result.append(row); continue
        outcomes = []
        for key in ("round_1", "round_2"):
            raw = row.get(key) or {}; check = check_round(raw, src)
            raw["postrun_validation_v2"] = check; outcomes.append(check)
        a, b = outcomes
        row["round_1_validated_label"] = a["validated_label"]; row["round_2_validated_label"] = b["validated_label"]
        if any(x["validated_status"] == "ANNOTATION_ERROR" for x in outcomes):
            status, label = "ANNOTATION_ERROR", None
        elif any(x["validated_status"] == "INCOMPLETE" for x in outcomes):
            status, label = "INCOMPLETE", None
        elif a["validated_label"] == b["validated_label"]:
            label = a["validated_label"]; status = "VALID_UNCERTAIN" if label == "UNCERTAIN" else "COMPLETE"
        else: status, label = "DISAGREEMENT", None
        row["validated_pair_status"] = status; row["validated_final_label"] = label
        row["postrun_validation_v2"] = {"round_1": a, "round_2": b}
        result.append(row)
    wjl(OUT / dest, result); return result

def p5(rows):
    byq = collections.defaultdict(list)
    for x in rows: byq[x["question_id"]].append(x)
    qs = []
    for qid, items in sorted(byq.items()):
        labels = [x.get("validated_final_label") for x in items]
        complete = (len(items) == 5 and {int(x["rank"]) for x in items} == {1,2,3,4,5}
                    and all(x.get("validated_pair_status") in {"COMPLETE","VALID_UNCERTAIN"} for x in items)
                    and all(x in {"RELEVANT","IRRELEVANT","UNCERTAIN"} for x in labels))
        u = labels.count("UNCERTAIN") if complete else 0; nrel = labels.count("RELEVANT") if complete else 0
        qs.append({"question_id":qid,"species":items[0].get("species"),"rank_count":len(items),"labels":labels,
                   "exact_p_at_5":nrel/5 if complete and not u else None,
                   "p5_lower_bound":nrel/5 if complete and u else None,
                   "p5_upper_bound":(nrel+u)/5 if complete and u else None,
                   "not_computable_reason":None if complete and not u else "true_uncertainty" if complete and u else "annotation_error_incomplete_disagreement_or_missing_rank",
                   "annotation_method":"AI_ASSISTED_ANNOTATION_NOT_HUMAN_GOLD"})
    vals = [x["exact_p_at_5"] for x in qs if x["exact_p_at_5"] is not None]
    species = collections.defaultdict(list)
    for x in qs: species[x["species"]].append(x["exact_p_at_5"])
    relna = sum(1 for row in rows for k in ("round_1","round_2")
                if (row.get(k,{}).get("stage1_parsed") or {}).get("relevance_label") == "RELEVANT"
                and (row.get(k,{}).get("stage1_parsed") or {}).get("species_applicability") == "not_applicable")
    mismatch = sum(1 for row in rows for k in ("round_1","round_2")
                   if (row.get(k,{}).get("postrun_validation_v2") or {}).get("explicit_species_mismatch"))
    accepted_wrong = sum(1 for row in rows for k in ("round_1","round_2")
                         if (row.get(k,{}).get("postrun_validation_v2") or {}).get("validated_label") == "RELEVANT"
                         and (row.get(k,{}).get("postrun_validation_v2") or {}).get("scope_guard_v2",{}).get("status") == "MISMATCH")
    return {"questions_in_pilot":len(qs),"contexts":len(rows),"rounds_per_context":2,
            "fully_completed_dual_round_contexts":sum(x["validated_pair_status"] in {"COMPLETE","VALID_UNCERTAIN"} for x in rows),
            "annotation_error_contexts":sum(x["validated_pair_status"]=="ANNOTATION_ERROR" for x in rows),
            "incomplete_contexts":sum(x["validated_pair_status"]=="INCOMPLETE" for x in rows),
            "disagreement_contexts":sum(x["validated_pair_status"]=="DISAGREEMENT" for x in rows),
            "post_validation_label_counts":dict(collections.Counter(x.get("validated_final_label") for x in rows)),
            "post_validation_pair_status_counts":dict(collections.Counter(x["validated_pair_status"] for x in rows)),
            "raw_judge_relevant_not_applicable_calls":relna,"explicit_species_mismatch_relevant_calls_intercepted":mismatch,
            "accepted_wrong_species_relevant_calls":accepted_wrong,"exact_p_at_5_n":len(vals),
            "mean_exact_p_at_5":sum(vals)/len(vals) if vals else None,
            "p5_with_valid_bounds_n":sum(x["p5_lower_bound"] is not None for x in qs),
            "per_species":{k:{"question_count":len(v),"exact_p5_n":sum(x is not None for x in v),
                              "mean_exact_p5":sum(x for x in v if x is not None)/sum(x is not None for x in v) if any(x is not None for x in v) else None}
                           for k,v in species.items()},"per_question":qs,
            "status":"AI_ASSISTED_ANNOTATION_NOT_HUMAN_GOLD"}

def uncertain():
    rows = r.phase_k_uncertain_analysis()
    old = {(x["question_id"],x["chunk_id"],int(x["rank"])):x for x in rjl(r.PHASE_K/"pilot_50_chunk_results_v2.jsonl") if x.get("first_pass_label")=="UNCERTAIN"}
    for x in rows:
        prev = old[(x["question_id"],x["chunk_id"],int(x["rank"]))]
        s = (prev.get("first_pass_species_assessment") or {}).get("status")
        primary = "SOURCE_METADATA_CONFLICT" if s=="SOURCE_CONFLICT" else "SPECIES_SCOPE_UNCLEAR"
        secondary=[]
        if not x.get("source_file_exists"): secondary.append("SOURCE_ORIGINAL_UNAVAILABLE")
        if not x.get("source_version"): secondary.append("DOCUMENT_VERSION_UNCLEAR")
        scope=(x.get("source_scope_reassessment") or {}).get("status")
        if scope=="UNCERTAIN": secondary.append("SPECIES_SCOPE_STILL_UNCLEAR_AFTER_ORIGINAL_REVIEW")
        if scope=="MISMATCH": secondary.append("SOURCE_SCOPE_MISMATCH_REQUIRES_SEMANTIC_REVIEW")
        x.update(phase_k_original_primary_reason_category=primary,primary_reason_category=primary,
                 current_secondary_blockers=sorted(set(secondary)),old_phase_k_assessment_status_preserved=s,
                 phase_k_original_label_preserved=True)
    summary={"source_phase":"Phase K","prior_uncertain_count":len(rows),
             "phase_k_original_primary_reason_counts":dict(collections.Counter(x["primary_reason_category"] for x in rows)),
             "current_secondary_blocker_counts":dict(collections.Counter(y for x in rows for y in x["current_secondary_blockers"])),
             "existing_original_scope_resolution_counts":dict(collections.Counter(x["resolution_status"] for x in rows)),
             "semantic_relevance_reclassified":False,"phase_k_labels_rewritten":False,"rows":rows}
    wj(OUT/"uncertain_reason_analysis.json",summary); return summary

def gate1_v2():
    p={"page_text":"","sha256":"test","source_locator":"test"}
    tests=[]
    def ck(name, actual, expected):
        if isinstance(actual, set): actual = sorted(actual)
        if isinstance(expected, set): expected = sorted(expected)
        tests.append({"name":name,"actual":actual,"expected":expected,"passed":actual==expected})
    ck("multispecies_declaration_not_chunk_applicability",r.assess_species_scope({"question_species":"烏魚","document_species":["石斑魚","鱸魚","烏魚"],"chunk_text":"七星鱸魚苗管理","source_title":"多魚種手冊"},p)["status"],"MISMATCH")
    ck("page_cooccurrence_not_chunk_scope",r.assess_species_scope({"question_species":"吳郭魚","document_species":[],"chunk_text":"石斑魚適溫","source_title":"養殖管理"},{"page_text":"吳郭魚及石斑魚","sha256":"test"})["status"],"MISMATCH")
    ck("specific_seabass_not_generic",r.species_mentions("金目鱸養殖") & {"generic_seabass","barramundi"},{"barramundi"})
    ck("mullet_tilapia_aliases",r.species_mentions("烏魚")=={"mullet"} and r.species_mentions("吳郭魚")=={"tilapia"},True)
    ck("explicit_general_claim",r.assess_species_scope({"question_species":"吳郭魚","document_species":[],"chunk_text":"各魚種養殖均應監測溶氧","source_title":"養殖管理"},p)["status"],"VERIFIED_GENERAL")
    ck("target_elsewhere_page_uncertain",r.assess_species_scope({"question_species":"虱目魚","document_species":[],"chunk_text":"魚塭設備應檢查","source_title":"養殖管理"},{"page_text":"虱目魚介紹；魚塭設備應檢查","sha256":"test"})["status"],"UNCERTAIN")
    ck("single_species_source_declaration",r.assess_species_scope({"question_species":"鰻魚","document_species":["鰻魚"],"chunk_text":"魚苗管理","source_title":"鰻魚養殖"},p)["status"],"APPLICABLE")
    chunk="烏魚放養"; spans=r.spans_for(chunk,"C",4)
    ck("invalid_or_cross_rank_span_rejected",r.resolve_selected_spans(chunk,spans,["SPAN_9999"])[1],"selected_span_id_not_in_program_bound_chunk")
    ck("relevant_without_span_rejected",r.resolve_selected_spans(chunk,spans,[])[1],"relevant_without_support_span")
    legacy=r.offline_tests()
    for x in legacy["tests"]: tests.append({"name":"legacy_"+x["name"],"passed":x["passed"],"expected":"pass","actual":x.get("detail")})
    return {"suite":"phase-l-gate1-v2","tests":tests,"passed":sum(t["passed"] for t in tests),
            "failed":sum(not t["passed"] for t in tests),"all_passed":all(t["passed"] for t in tests),
            "synthetic_tests_excluded_from_research_denominator":True}

def main():
    sm=source_rows()
    ten=[]
    for row in rjl(OUT/"pilot_10_chunk_results_v3.jsonl"):
        src=sm.get((row["question_id"],row["chunk_id"],int(row["rank"])))
        if src is None:
            row["postrun_validation_v2"]={"validated_status":"SOURCE_MISSING","validated_label":None}
        else:
            row["postrun_validation_v2"]=check_round(row,src)
        row["validated_final_label"]=row["postrun_validation_v2"].get("validated_label")
        row["validated_status_v2"]=row["postrun_validation_v2"].get("validated_status")
        ten.append(row)
    wjl(OUT/"pilot_10_chunk_results_v3_reconciled.jsonl",ten)
    fifty=reconcile("pilot_50_chunk_results_v3.jsonl","pilot_50_chunk_results_v3_reconciled.jsonl",sm)
    ps=p5(fifty); wj(OUT/"context_precision_pilot_v3.json",ps)
    ua=uncertain(); g1=gate1_v2(); wj(OUT/"gate1_offline_regression_v2.json",g1)
    g2={"fixed_real_chunks":len(ten),"valid_single_chunk_annotations":sum(x.get("validated_status_v2") in {"VALID","VALID_UNCERTAIN"} for x in ten),
        "all_identity_bindings_valid":all(x.get("identity_binding_valid") is True for x in ten),
        "all_relevant_quotes_exact":all(not ((x.get("stage1_parsed") or {}).get("relevance_label")=="RELEVANT") or (x.get("postrun_validation_v2") or {}).get("exact_span_valid") or (x.get("postrun_validation_v2") or {}).get("scope_guard_v2",{}).get("status")=="MISMATCH" for x in ten),
        "passed":len(ten)==10 and all(x.get("validated_status_v2") in {"VALID","VALID_UNCERTAIN"} for x in ten) and all(x.get("identity_binding_valid") is True for x in ten),
        "human_gold":False,"raw_judge_fields_preserved":True}
    wj(OUT/"gate2_decision_v2.json",g2)
    states=collections.Counter(x["validated_pair_status"] for x in fifty)
    g3={"fixed_contexts":len(fifty),"raw_two_round_calls":sum(bool(x.get("round_1",{}).get("stage1_completed")) and bool(x.get("round_2",{}).get("stage1_completed")) for x in fifty),
        "raw_round_status_pair_counts":dict(collections.Counter(x.get("round_1",{}).get("status","MISSING")+"/"+x.get("round_2",{}).get("status","MISSING") for x in fifty)),
        "validated_dual_round_contexts":sum(x in {"COMPLETE","VALID_UNCERTAIN"} for x in states.elements()),
        "pair_status_counts":dict(states),"annotation_errors":states["ANNOTATION_ERROR"],"incomplete":states["INCOMPLETE"],
        "identity_bindings_all_correct":all(x.get("round_1",{}).get("identity_binding_valid") is True and x.get("round_2",{}).get("identity_binding_valid") is True for x in fifty),
        "accepted_wrong_species_relevant":ps["accepted_wrong_species_relevant_calls"],
        "passed":len(fifty)==50 and all(x["validated_pair_status"] in {"COMPLETE","VALID_UNCERTAIN"} for x in fifty) and g1["all_passed"] and g2["passed"] and ps["accepted_wrong_species_relevant_calls"]==0,
        "human_gold":False}
    g3["decision"]="GO_900_BATCH" if g3["passed"] else "NO_GO_900_BATCH"; wj(OUT/"gate3_decision.json",g3)
    base=r.baseline_recheck(); wj(OUT/"frozen_baseline_summary_v2.json",base)
    report={"gate1":g1,"gate2":g2,"gate3":g3,"p5_summary":{k:v for k,v in ps.items() if k!="per_question"},
            "uncertain_summary":{k:v for k,v in ua.items() if k!="rows"},"baseline":base}
    wj(OUT/"phase_l_postrun_summary.json",report)
    stamp=dt.datetime.now().astimezone().isoformat(timespec="seconds")
    (OUT/"annotation_reliability_report.md").write_text(
        "# Phase L 標註可靠性稽核\n\n"
        f"稽核時間：{stamp}\n\n- Gate 1：{g1['passed']}/{len(g1['tests'])}，全通過={g1['all_passed']}。\n"
        f"- Gate 2：{g2['valid_single_chunk_annotations']}/10 單筆標註有效，通過={g2['passed']}。\n"
        f"- Gate 3：{g3['validated_dual_round_contexts']}/50 有效雙輪；標註錯誤={g3['annotation_errors']}、未完成={g3['incomplete']}；通過={g3['passed']}。\n"
        f"- 50 段中 Relevant+not_applicable 原始輸出={ps['raw_judge_relevant_not_applicable_calls']} 次；明確 mismatch 被攔截={ps['explicit_species_mismatch_relevant_calls_intercepted']} 次；錯誤魚種 Relevant 被接受={ps['accepted_wrong_species_relevant_calls']} 次。\n"
        f"- 精確 P@5={ps['exact_p_at_5_n']}/10，平均={ps['mean_exact_p_at_5']}；此為 AI-assisted，不是 Human Gold。\n"
        f"- Phase K 22 筆原始主要原因={ua['phase_k_original_primary_reason_counts']}；次要阻塞={ua['current_secondary_blocker_counts']}。\n"
        f"- Frozen baseline={base['unchanged']}/{base['manifest_entries']}，SQLite hash 一致={base['sqlite_matches']}。\n\n"
        "原始 Judge 回覆及 Phase K 標籤均保留；守門後判定存於 pilot_*_reconciled.jsonl。沒有啟動 900 段批次。\n",encoding="utf-8")
    (OUT/"phase_l_final_report.md").write_text(
        "# Phase L 最終報告\n\n"
        f"- Span ID 問題：舊截短 ID 相似且標籤/引用同回合輸出；新程式使用程式綁定的 chunk-local span。離線回歸 {g1['passed']}/{len(g1['tests'])}。\n"
        f"- 固定10段：{g2['valid_single_chunk_annotations']}/10 單筆標註有效；Gate 2={g2['passed']}。\n"
        f"- 固定50段：兩輪呼叫完成 {g3['raw_two_round_calls']}/50；守門後有效雙輪 {g3['validated_dual_round_contexts']}/50；狀態={ps['post_validation_label_counts']}；錯誤={g3['annotation_errors']}。\n"
        f"- Judge 原始 Relevant+not_applicable={ps['raw_judge_relevant_not_applicable_calls']}；來源 mismatch Relevant 被攔截={ps['explicit_species_mismatch_relevant_calls_intercepted']}；錯誤物種 Relevant 被接受={ps['accepted_wrong_species_relevant_calls']}。\n"
        f"- 精確 P@5={ps['exact_p_at_5_n']}/10，平均={ps['mean_exact_p_at_5']}；有合法上下界={ps['p5_with_valid_bounds_n']} 題。\n"
        f"- Phase K 原22筆 Uncertain 的原始原因={ua['phase_k_original_primary_reason_counts']}；次要阻塞={ua['current_secondary_blocker_counts']}。\n"
        f"- 擴大900段：{'可' if g3['passed'] else '不可'}（Gate 3={g3['passed']}）。Human Gold=0。\n"
        f"- Frozen Manifest={base['unchanged']}/{base['manifest_entries']}；SQLite SHA-256 一致={base['sqlite_matches']}。\n\n"
        "P@5 僅為 AI 輔助試點結果，不是人工 Gold。沒有重跑 Generator，也未修改 Corpus/E4、Production、SQLite 或歷史 Phase K 資料。\n",encoding="utf-8")
    comp=rj(OUT/"compatibility.json")
    comp.update({"postrun_reconciliation":True,"gate1_v2_passed":g1["all_passed"],"gate2_v2_passed":g2["passed"],
                 "gate3_v2_passed":g3["passed"],"scale_to_900":g3["passed"],"frozen_manifest_recheck":f"{base['unchanged']}/{base['manifest_entries']}",
                 "sqlite_sha256_matches_expected":base["sqlite_matches"],"raw_judge_fields_preserved":True,
                 "phase_k_labels_modified":False,"human_gold":0})
    wj(OUT/"compatibility.json",comp)
    val=rj(OUT/"run_validation.json")
    val.update({"postrun_reconciled":True,"gate1_v2_passed":g1["all_passed"],"gate2_v2_passed":g2["passed"],
                "gate3_v2_passed":g3["passed"],"p5_exact_n_v2":ps["exact_p_at_5_n"],"p5_mean_v2":ps["mean_exact_p_at_5"],
                "frozen_636_unchanged":base["all_636_unchanged"],"sqlite_matches":base["sqlite_matches"]})
    wj(OUT/"run_validation.json",val)
    print(json.dumps({"gate1":g1["all_passed"],"gate1_n":len(g1["tests"]),"gate2":g2["passed"],"gate3":g3["passed"],
                      "valid_dual_50":g3["validated_dual_round_contexts"],"errors":g3["annotation_errors"],
                      "p5_n":ps["exact_p_at_5_n"],"p5_mean":ps["mean_exact_p_at_5"],"labels":ps["post_validation_label_counts"],
                      "uncertain":ua["phase_k_original_primary_reason_counts"],"baseline":f"{base['unchanged']}/{base['manifest_entries']}"},
                     ensure_ascii=False))

if __name__=="__main__": main()
