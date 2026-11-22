"""Frozen metric definitions; existing independent Judge; raw/system separation."""
import sys,json,ast,time,math,collections
from decimal import Decimal
sys.dont_write_bytecode=True
from fair_grounded_rag_final import W,I,OLLAMA,jl,write,append,digest,parse_arithmetic,content_problem,unload_all
from execute_frozen_run import verify_freeze
import requests,jsonschema
C={}
for node in ast.parse((I/'score_frozen_run.py').read_text(encoding='utf-8')).body:
 if isinstance(node,ast.Assign):
  for t in node.targets:
   if isinstance(t,ast.Name) and t.id in {'J_SYSTEM','J_POLICY','L_POLICY','JS','LS','JUDGE','JDIGEST','BGE','BDIGEST'}:C[t.id]=ast.literal_eval(node.value)
J_SYSTEM,J_POLICY,L_POLICY,JS,LS,JUDGE,JDIGEST,BGE,BDIGEST=[C[k] for k in ['J_SYSTEM','J_POLICY','L_POLICY','JS','LS','JUDGE','JDIGEST','BGE','BDIGEST']]

def visible(g,layer):
 p=g['result'] if layer=='system' else g['validation'].get('parsed_model_response')
 if not isinstance(p,dict):return None,'UNPARSED_RAW_OUTPUT'
 if layer=='system':
  if p['answer_origin'] in {'ABSTAINED','VALIDATION_FAILED'}:return None,p['answer_origin']
  a=p['final_answer']
 else:
  if p.get('answer_status')=='INSUFFICIENT_EVIDENCE':return None,'MODEL_ABSTENTION'
  a=p.get('answer')
 if not isinstance(a,str) or not a.strip():return None,'EMPTY_VISIBLE_ANSWER'
 bad=content_problem(a,g['question']);return (None,bad) if bad else (a.strip(),None)

def chat(messages,schema,key,kind):
 payload={'model':JUDGE,'messages':messages,'stream':True,'format':schema,'keep_alive':'30m','options':{'temperature':0,'top_p':1,'seed':21021,'num_predict':512,'num_ctx':8192}}
 errors=[]
 for attempt in range(1,3):
  parts=[];events=[];body={};error=None;parsed=None;t=time.perf_counter()
  try:
   with requests.post(OLLAMA+'/api/chat',json=payload,stream=True,timeout=(30,600)) as response:
    response.raise_for_status()
    for line in response.iter_lines(chunk_size=1):
     if not line:continue
     ev=json.loads(line);events.append({'elapsed_seconds':time.perf_counter()-t,'event':ev});parts.append((ev.get('message') or {}).get('content',''))
     if ev.get('error'):raise RuntimeError(ev['error'])
     if ev.get('done'):body=ev
   if not body.get('done'):raise ValueError('JUDGE_STREAM_MISSING_DONE')
   parsed=json.loads(''.join(parts));jsonschema.validate(parsed,schema)
  except Exception as exc:error=f'{type(exc).__name__}: {exc}';errors.append(error)
  append('judge_raw_attempts.jsonl',{'input_key':key,'kind':kind,'attempt':attempt,'model':JUDGE,'digest':JDIGEST,'payload':payload,'raw':''.join(parts),'stream':events,'error':error,'wall_seconds':time.perf_counter()-t})
  if error is None:return {'status':'scored','scores':parsed,'errors':errors,'attempt_count':attempt,'judge_tag':JUDGE,'judge_digest':JDIGEST,'prompt_sha256':digest(messages)}
 return {'status':'judge_error','scores':None,'errors':errors,'attempt_count':2,'judge_tag':JUDGE,'judge_digest':JDIGEST,'prompt_sha256':digest(messages)}

def score_professional(gens,refs):
 for metric in ['arithmetic','logical']:
  fn=f'{metric}_accuracy_detailed.jsonl';old=jl(W/fn) if (W/fn).exists() else [];done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};cache={x['input_key']:x['evaluation'] for x in old if x.get('evaluation',{}).get('status')=='scored'}
  if metric=='logical':unload_all()
  for g in gens:
   ref=refs[g['question_id']];calc=ref.get('expected_calculation')
   if (metric=='arithmetic' and not calc) or (metric=='logical' and not ref.get('logical_rubric')):continue
   for layer in ['model','system']:
    if (g['question_id'],g['model_id'],layer) in done:continue
    answer,reason=visible(g,layer);row={'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'species':g['species'],'category':g['category'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'source_group_ids':g['source_group_ids'],'rubric_sha256':ref['rubric_sha256'],'verification_level':'AUTO_SOURCE_VERIFIED; AI_ASSISTED; NOT_HUMAN_GOLD','verdict':'not_evaluable','reason':reason,'fixed_denominator_success':False,'validated_task_success':False,'raw_answer_text':answer}
    if answer and metric=='arithmetic':
     a,b=Decimal(calc['a']),Decimal(calc['b']);result={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert result==Decimal(calc['expected']);check=parse_arithmetic(answer,calc)
     row.update(formula=calc,decimal_reference_result=str(result),numeric_check=check,verdict=('correct' if check['correct'] else 'incorrect') if check['evaluable'] else 'not_evaluable',reason=check['reason'])
    elif answer:
     source=[{k:s.get(k) for k in ['source_id','source_version','exact_evidence_span','evidence_locator']} for s in ref['evidence_spans']]
     messages=[{'role':'system','content':J_SYSTEM},{'role':'user','content':L_POLICY+f"\nQuestion: {g['question']}\nSpecies: {g['species']}\nFrozen rubric: {json.dumps(ref['logical_rubric'],ensure_ascii=False)}\nSource: {json.dumps(source,ensure_ascii=False)}\nAnswer: {answer}"}];key=digest(messages);reused=key in cache;ev=cache[key] if reused else chat(messages,LS,key,'LOGICAL');row.update(input_key=key,evaluation=ev,identical_input_cache_reuse=reused)
     if ev['status']=='scored':
      cache[key]=ev;s=ev['scores'];v=s['verdict']
      if v=='correct' and (not s['required_conditions_satisfied'] or s['material_contradictions']):v='not_evaluable';reason='JUDGE_INTERNAL_CONTRADICTION'
      else:reason=s['reason']
      row.update(verdict=v,reason=reason)
     else:row['reason']='JUDGE_ERROR'
    row['fixed_denominator_success']=row['verdict']=='correct';vs=g['result']['validation_status'];valid=g['result']['answer_status']=='ANSWERED_GROUNDED' and (layer=='system' or (g['result']['answer_origin']=='MODEL_GENERATED' and vs['raw_json_valid'] and vs['raw_citation_valid']));row['validated_task_success']=row['verdict']=='correct' and valid
    append(fn,row);print('SCORE',metric,g['model_id'],g['question_id'],layer,row['verdict'],flush=True)
 unload_all()

def score_quality(gens,ctx):
 fn='judge_quality_detailed.jsonl';old=jl(W/fn) if (W/fn).exists() else [];done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};cache={x['input_key']:x['evaluation'] for x in old if x.get('evaluation',{}).get('status')=='scored'};unload_all()
 for i,g in enumerate(gens):
  r=ctx[g['question_id']];ct='\n\n'.join(f"[{c['chunk_id']}] {c['source_version']} {c['exact_locator']}\n{c['source_quote']}" for c in r['top5'])
  # Judge receives exactly the source_quote text supplied to Generator, not hidden full-chunk text.
  for layer in ['model','system']:
   if (g['question_id'],g['model_id'],layer) in done:continue
   answer,reason=visible(g,layer);row={'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'context_digest':g['context_digest'],'human_gold':False,'faithfulness':None,'judge_answer_relevance':None,'reason':reason,'evidence_text_policy':'Exactly source_quote fields sent to Generator; no hidden full chunk or Gold'}
   if answer:
    messages=[{'role':'system','content':J_SYSTEM},{'role':'user','content':J_POLICY+f"\nQuestion: {g['question']}\nContext:\n{ct}\nAnswer:\n{answer}"}];key=digest(messages);reused=key in cache;ev=cache[key] if reused else chat(messages,JS,key,'QUALITY')
    if ev['status']=='scored':cache[key]=ev;row.update(faithfulness=ev['scores']['faithfulness'],judge_answer_relevance=ev['scores']['answer_relevance'])
    row.update(evaluation=ev,input_key=key,identical_input_cache_reuse=reused)
   append(fn,row)
  if (i+1)%10==0:print('QUALITY',i+1,len(gens),flush=True)
 unload_all()

def bge(gens):
 fn='bge_relevance_detailed.jsonl';old=jl(W/fn) if (W/fn).exists() else [];done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};pending=[];unload_all()
 for g in gens:
  for layer in ['model','system']:
   key=g['question_id'],g['model_id'],layer
   if key in done:continue
   answer,reason=visible(g,layer)
   if answer:pending.append((g,layer,answer))
   else:append(fn,{'run_id':g['run_id'],'question_id':key[0],'model_id':key[1],'answer_layer':layer,'cosine':None,'status':'NOT_EVALUABLE','reason':reason})
 for start in range(0,len(pending),12):
  batch=pending[start:start+12];texts=[t for g,l,a in batch for t in [g['question'],a]];response=requests.post(OLLAMA+'/api/embed',json={'model':BGE,'input':texts,'truncate':False,'keep_alive':'30m'},timeout=600);response.raise_for_status();vectors=response.json()['embeddings'];assert len(vectors)==len(texts) and all(len(v)==1024 for v in vectors)
  for i,(g,layer,answer) in enumerate(batch):
   qv,av=vectors[2*i:2*i+2];norm=lambda v:math.sqrt(sum(x*x for x in v));co=sum(x*y for x,y in zip(qv,av))/(norm(qv)*norm(av));append(fn,{'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'cosine':co,'status':'SCORED_VISIBLE_NONABSTAINED_ANSWER','model':BGE,'digest':BDIGEST,'dimension':1024,'normalization':'Explicit cosine; no prefix; no thinking, Gold, Context or refusal text','answer_sha256':digest(answer)})
  print('BGE',min(start+12,len(pending)),len(pending),flush=True)
 unload_all()

def main():
 verify_freeze();gens=jl(W/'generator_final_results_720.jsonl');assert len(gens)==len({(g['question_id'],g['model_id']) for g in gens})==720;refs={r['question_id']:r for r in jl(W/'verified_reference_answers_v3.jsonl')};ctx={r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')}
 tags={x['name']:x for x in requests.get(OLLAMA+'/api/tags',timeout=30).json()['models']};assert tags[JUDGE]['digest']==JDIGEST and tags[BGE]['digest']==BDIGEST and JDIGEST not in {g['model_digest'] for g in gens}
 bge(gens);score_professional(gens,refs);score_quality(gens,ctx)
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
