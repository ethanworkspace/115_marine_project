import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'; X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
core=load('phase_w_core',W/'phase_w_core.py'); app=load('rag_v3_phase_w',W/'app'/'rag_v3_phase_w.py'); eng=app.RAGEngine()
r=next(x for x in core.read_jsonl(W/'smoke_retrieval_results.jsonl') if x['question_id']=='SMOKE-EVIDENCE-GROUPER')
q='該片段記載的鞍帶石斑建議放養密度範圍及單位為何？請只根據片段回答。'
row=eng.answer_with_retrieval(q,r['species'],r['category'],'M2',r,'phase_x_m2_direct_regression',evaluate_refusal=True)
a=(row.get('answer') or '').replace(',','').replace('，','')
valid=('10000' in a and '30000' in a and ('公頃' in a or '尾' in a))
res={'case_id':'M2-GROUPER-DIRECT-REPHRASE','model_id':'M2','question':q,'context_count':len(r.get('reranked_top5',[])),'context_chunk_ids':[c['chunk_id'] for c in r.get('reranked_top5',[])],'context_texts':[c.get('content') for c in r.get('reranked_top5',[])],'source_ids':[c.get('source_id') for c in r.get('reranked_top5',[])],'generator_called':row.get('generator_called'),'raw_model_status':row.get('model_reported_status'),'effective_status':row.get('status'),'answer':row.get('answer'),'citations':row.get('citations'),'citation_validation':row.get('citation_validation'),'parse_error':row.get('parse_error'),'content_match_check':valid,'status':'PASS' if row.get('status')=='answered' and valid and row.get('citation_validation',{}).get('valid') else 'FAIL','prompt_sha256':row.get('prompt_sha256'),'timing':row.get('timing'),'note':'Same single applicable researcher-authored fact card; only question wording changed. This is diagnostic regression, not a score.'}
p=X/'m2_api_regression.json'; obj=json.loads(p.read_text(encoding='utf-8')); obj['calls']+=1; obj['results'].append(res); p.write_text(json.dumps(obj,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'case_id':res['case_id'],'context_count':res['context_count'],'raw_model_status':res['raw_model_status'],'effective_status':res['effective_status'],'content_match_check':res['content_match_check'],'citation_validation':res['citation_validation'],'status':res['status'],'answer_ascii':(res.get('answer') or '').encode('unicode_escape').decode()},ensure_ascii=True,indent=2))
