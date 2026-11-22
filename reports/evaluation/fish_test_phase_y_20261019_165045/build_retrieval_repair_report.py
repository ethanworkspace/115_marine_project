import pathlib,json,collections,sys
sys.stdout.reconfigure(encoding='utf-8')
E=pathlib.Path('reports/evaluation'); Y=E/'fish_test_phase_y_20261019_165045'; X=E/'fish_test_phase_x_20261019_162147'; W=E/'fish_test_phase_w_20261019_133804'; V=E/'fish_test_phase_v_20261018_224918'
def read(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
v={r['question_id']:r for r in read(V/'retrieval_results_v3_final.jsonl')}; w={r['question_id']:r for r in read(W/'retrieval_results_v3_updated.jsonl')}; y={r['question_id']:r for r in read(Y/'retrieval_results_phase_y.jsonl')}; x={r['question_id']:r for r in read(X/'retrieval_coverage_regression_180.jsonl')}
def cc(r):return len(r.get('reranked_top5') or [])
out=[]
for qid,vr in v.items():
 wr=w[qid]; yr=y[qid]; vx=cc(vr);wx=cc(wr);yx=cc(yr)
 if vx>wx and yx==vx: fix='RESTORED_TO_PHASE_V_CONTEXT_COUNT'
 elif vx>wx and yx>wx: fix='PARTIALLY_RESTORED'
 elif vx>wx and yx==wx: fix='REGRESSION_REMAINS'
 else: fix='NO_VW_CONTEXT_COUNT_REGRESSION'
 if not yr.get('allowed_source_ids') and yr.get('corpus_applicable_chunk_count',0)==0: stage='NO_SOURCE_ALLOWLIST_OR_SOURCE_PROFILE'
 elif yr.get('corpus_applicable_chunk_count',0)==0: stage='SOURCE_PRESENT_BUT_METADATA_SCOPE_FILTER_REJECTED'
 elif yr.get('bm25_candidate_count',0)==0 and yr.get('dense_candidate_count',0)==0: stage='ELIGIBLE_CHUNKS_BUT_BM25_AND_DENSE_RECALL_ZERO'
 elif yx<5: stage='APPLICABLE_CORPUS_POOL_BELOW_TOP5'
 elif yx==5: stage='TOP5_AVAILABLE'
 else: stage='OTHER_RETRIEVAL_STAGE'
 out.append({'question_id':qid,'species':yr.get('species'),'category':yr.get('category'),'question_text':yr.get('question_text'),'phase_v_context_count':vx,'phase_w_context_count':wx,'phase_y_context_count':yx,'v_to_w_change':'down' if vx>wx else ('up' if vx<wx else 'same'),'y_vs_w_context_change':yx-wx,'repair_status':fix,'phase_x_diagnosed_stage':x[qid].get('diagnosed_stage'),'phase_x_failure_reason':x[qid].get('phase_w_failure_reason'),'phase_v_allowed_source_ids':x[qid].get('phase_v_source_allowlist'),'phase_w_allowed_source_ids':wr.get('allowed_source_ids',x[qid].get('phase_w_allowed_source_ids')),'phase_y_allowed_source_ids':yr.get('allowed_source_ids'),'phase_y_applicable_sources':yr.get('corpus_applicable_source_count'),'phase_y_applicable_chunks':yr.get('corpus_applicable_chunk_count'),'phase_y_bm25_candidates':yr.get('bm25_candidate_count'),'phase_y_dense_candidates':yr.get('dense_candidate_count'),'phase_y_rrf_candidates':yr.get('rrf_candidate_count'),'phase_y_source_qualified':yr.get('source_qualification_pass_count'),'phase_y_species_qualified':yr.get('species_applicability_pass_count'),'phase_y_reranker_candidates':yr.get('reranker_candidate_count'),'phase_y_final_top5':yx,'phase_y_final_sources':list(dict.fromkeys(c.get('source_id') for c in yr.get('reranked_top5') or [])),'phase_y_failure_reason':yr.get('retrieval_failure_reason'),'phase_y_rejection_reasons':yr.get('scope_rejection_reasons'),'diagnosis_stage':stage,'query_text_identical_v_w_y':vr.get('query')==wr.get('query')==yr.get('query'),'corpus_version_v_w_y':[vr.get('corpus_version'),wr.get('corpus_version'),yr.get('corpus_version')],'source_crosswalk_overlay':'phase_y_source_crosswalk_overlay_v1'})
(Y/'retrieval_filter_fix_180.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in out),encoding='utf-8')
summary={'question_count':len(out),'phase_v_any':sum(cc(r) for r in v.values()) and sum(cc(r)>0 for r in v.values()),'phase_w_any':sum(cc(r)>0 for r in w.values()),'phase_y_any':sum(cc(r)>0 for r in y.values()),'phase_v_full':sum(cc(r)==5 for r in v.values()),'phase_w_full':sum(cc(r)==5 for r in w.values()),'phase_y_full':sum(cc(r)==5 for r in y.values()),'v_to_w_changes':dict(collections.Counter(r['v_to_w_change'] for r in out)),'repair_status':dict(collections.Counter(r['repair_status'] for r in out)),'diagnosis_stage':dict(collections.Counter(r['diagnosis_stage'] for r in out)),'phase_v_to_y_transition':{f'{a}->{b}':n for (a,b),n in collections.Counter((r['phase_v_context_count'],r['phase_y_context_count']) for r in out).items()},'phase_y_minus_w_total_context_rows':sum(r['phase_y_context_count']-r['phase_w_context_count'] for r in out),'summary_note':'Counts describe available retrieval contexts, not evidence relevance or answer correctness. Phase V broad retrieval contained cross-species candidates; no unsafe candidate was restored solely to match V.'}
(Y/'retrieval_coverage_repair_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))

