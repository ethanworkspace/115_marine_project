import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'; X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
core=load('phase_w_core_xreg',W/'phase_w_core.py');app=load('phase_x_rag_v3',X/'phase_x_rag_v3.py');eng=app.RAGEngine(); r=next(x for x in core.read_jsonl(W/'smoke_retrieval_results.jsonl') if x['question_id']=='SMOKE-EVIDENCE-GROUPER')
q='依鞍帶石斑資料，放養密度建議範圍是多少尾/公頃？'
row=eng.answer_with_retrieval(q,r['species'],r['category'],'M2',r,'phase_x_prompt_regression_m2',evaluate_refusal=True)
a=(row.get('answer') or '').replace(',','').replace('，','')
content_match=('10000' in a and '30000' in a and ('公頃' in a or '尾' in a))
res={'case_id':'M2-GROUPER-DIRECT-PROMPT-REPAIR','model_id':'M2','question':q,'context_count':len(r.get('reranked_top5',[])),'context_chunk_ids':[c['chunk_id'] for c in r.get('reranked_top5',[])],'context_texts':[c.get('content') for c in r.get('reranked_top5',[])],'source_ids':[c.get('source_id') for c in r.get('reranked_top5',[])],'generator_called':row.get('generator_called'),'raw_model_status':row.get('model_reported_status'),'effective_status':row.get('status'),'answer':row.get('answer'),'citations':row.get('citations'),'citation_validation':row.get('citation_validation'),'parse_error':row.get('parse_error'),'content_match_check':content_match,'prompt_sha256':row.get('prompt_sha256'),'prompt':row.get('prompt'),'timing':row.get('timing'),'status':'PASS' if row.get('status')=='answered' and content_match and row.get('citation_validation',{}).get('valid') else 'FAIL','note':'Single-context real M2 regression on the one direct researcher-authored fact card; safety gates remain enabled. This tests prompt behavior only and is not a professional-accuracy score.'}
(X/'m2_prompt_repair_regression.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':res['status'],'raw_model_status':res['raw_model_status'],'effective_status':res['effective_status'],'answer':res.get('answer'),'citations':res.get('citations'),'citation_validation':res.get('citation_validation'),'prompt_sha256':res.get('prompt_sha256'),'timing':res.get('timing')},ensure_ascii=False,indent=2))
