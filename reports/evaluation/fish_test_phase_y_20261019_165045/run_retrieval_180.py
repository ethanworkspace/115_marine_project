import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
Y=Path(__file__).resolve().parent
W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
core=load('phase_y_core_retrieval',Y/'phase_y_core.py')
old=[json.loads(s) for s in (W/'retrieval_results_v3_updated.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
questions=[{'question_id':r['question_id'],'species':r.get('species'),'category':r.get('category'),'question_text':r.get('question_text','')} for r in old]
new=core.retrieve_180(questions,output_path=Y/'retrieval_results_phase_y.jsonl')
new_by={r['question_id']:r for r in new}
diag=[]
for o in old:
 n=new_by[o['question_id']]; oldtop=o.get('reranked_top5',[]); top=n.get('reranked_top5',[])
 diag.append({'question_id':o['question_id'],'species':o.get('species'),'category':o.get('category'),'question_text':o.get('question_text'),'phase_w_context_count':len(oldtop),'phase_y_context_count':len(top),'delta':len(top)-len(oldtop),'change':'up' if len(top)>len(oldtop) else ('down' if len(top)<len(oldtop) else 'same'),'phase_w_source_ids':list(dict.fromkeys(c.get('source_id') for c in oldtop)),'phase_y_source_ids':list(dict.fromkeys(c.get('source_id') for c in top)),'bm25_candidates':n.get('bm25_candidate_count'),'dense_candidates':n.get('dense_candidate_count'),'rrf_candidates':n.get('rrf_candidate_count'),'source_qualified':n.get('source_qualification_pass_count'),'species_qualified':n.get('species_applicability_pass_count'),'reranker_candidates':n.get('reranker_candidate_count'),'final_top5':len(top),'phase_w_failure_reason':o.get('retrieval_failure_reason'),'phase_y_failure_reason':n.get('retrieval_failure_reason'),'phase_y_stage_reasons':n.get('scope_rejection_reasons'),'phase_y_retrieval_status':n.get('retrieval_status'),'corpus_version_w':o.get('corpus_version'),'corpus_version_y':n.get('corpus_version'),'same_corpus':o.get('corpus_version')==n.get('corpus_version'),'query_text_identical':o.get('query')==n.get('query'),'source_crosswalk_sidecar_version':'phase_y_crosswalk_overlay_v1'})
(Y/'retrieval_filter_fix_180.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in diag),encoding='utf-8')
print(json.dumps({'questions':len(new),'phase_w_any':sum(bool(r.get('reranked_top5')) for r in old),'phase_y_any':sum(bool(r.get('reranked_top5')) for r in new),'phase_w_full':sum(len(r.get('reranked_top5',[]))==5 for r in old),'phase_y_full':sum(len(r.get('reranked_top5',[]))==5 for r in new),'changes':{x:sum(d['change']==x for d in diag) for x in ('up','same','down')},'corpus_versions':sorted({r.get('corpus_version') for r in new})},ensure_ascii=False,indent=2))
