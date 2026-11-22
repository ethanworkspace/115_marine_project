from __future__ import annotations
import importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'; X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
core=load('phase_w_core',W/'phase_w_core.py'); app=load('rag_v3_phase_w',W/'app'/'rag_v3_phase_w.py'); eng=app.RAGEngine()
retrievals={x['question_id']:x for x in core.read_jsonl(W/'smoke_retrieval_results.jsonl')}
cases=[('SMOKE-EVIDENCE-GROUPER','M2'),('SMOKE-NO-EVIDENCE','M2')]
results=[]
for qid,mid in cases:
 r=retrievals[qid]
 row=eng.answer_with_retrieval(r['question_text'],r['species'],r['category'],mid,r,'phase_x_m2_regression',evaluate_refusal=True)
 contexts=r.get('reranked_top5',[])
 if qid=='SMOKE-EVIDENCE-GROUPER':
  text=(row.get('answer') or '').replace(',','').replace('，','')
  answer_supported=('10000' in text and '30000' in text and ('公頃' in text or '尾' in text))
  cites=all(c.get('chunk_id') in {x.get('chunk_id') for x in contexts} for c in row.get('citations',[]))
 else:
  answer_supported=(row.get('status')=='abstain' and not row.get('citations'))
  cites=(row.get('status')=='abstain' and not row.get('citations'))
 results.append({
  'case_id':qid,'model_id':mid,'model_tag':row.get('model_tag'),'model_digest':row.get('model_digest'),
  'question':r.get('question_text'),'species':r.get('species'),'context_count':len(contexts),
  'context_sources':[{'source_id':c.get('source_id'),'version':c.get('source_version'),'locator':c.get('page_or_locator'),'chunk_id':c.get('chunk_id'),'text':c.get('content')} for c in contexts],
  'source_usage_scope':'TFRI M17 researcher-authored concise factual card; narrow grouper scope; not full-text manual indexing.',
  'generator_called':row.get('generator_called'),'raw_model_status':row.get('model_reported_status'),'effective_status':row.get('status'),
  'answer':row.get('answer'),'citations':row.get('citations'),'citation_validation':row.get('citation_validation'),
  'parse_error':row.get('parse_error'),'timing':row.get('timing'),'prompt_sha256':row.get('prompt_sha256'),
  'expected_answer_elements':'For grouper evidence case: 10,000–30,000 tails per hectare; adjust according to water quality and culture experience.' if qid.endswith('GROUPER') else 'No-context case must abstain without a citation.',
  'content_match_check':answer_supported,'citation_binding_check':cites,
  'status':'PASS' if (row.get('status')=='answered' and answer_supported and cites and row.get('citation_validation',{}).get('valid')) or (qid.endswith('NO-EVIDENCE') and row.get('status')=='abstain' and not row.get('citations')) else 'FAIL',
  'limitations':['One-case regression is not professional accuracy evidence.','AI generation is not Human Gold.','The supporting grouper text is a narrow research fact card, not a full-text index permission.']
 })
(X/'m2_api_regression.json').write_text(json.dumps({'run_id':'phase_x_m2_answerability_regression','calls':len(results),'results':results,'conclusion':'A positive-context M2 response is considered grounded only if its specific range matches the pre-existing researcher-authored card and its citation ID maps to that single supplied chunk. Empty context is tested for abstention; this does not estimate answer quality.'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'calls':len(results),'results':[{'case_id':x['case_id'],'context_count':x['context_count'],'raw_model_status':x['raw_model_status'],'effective_status':x['effective_status'],'answer':x['answer'],'content_match_check':x['content_match_check'],'citation_binding_check':x['citation_binding_check'],'status':x['status']} for x in results]},ensure_ascii=False,indent=2))
