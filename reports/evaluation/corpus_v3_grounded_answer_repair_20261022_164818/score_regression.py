"""Pre-generation frozen scoring policy. Existing independent Judge, no new arbiter."""
import sys,json,ast,time,collections
from decimal import Decimal
from pathlib import Path
sys.dont_write_bytecode=True
from fair_grounded_rag import W,I,OLLAMA,MODELS,jl,write,append,digest,parse_arithmetic,content_problem,unload_all
from run_regression import verify_freeze
import requests,jsonschema

# Read literal policy only: importing the historical runner would risk writing there.
constants={}
for node in ast.parse((I/'score_frozen_run.py').read_text(encoding='utf-8')).body:
 if isinstance(node,ast.Assign):
  for target in node.targets:
   if isinstance(target,ast.Name) and target.id in {'J_SYSTEM','L_POLICY','LS','JUDGE','JDIGEST'}:constants[target.id]=ast.literal_eval(node.value)
J_SYSTEM,L_POLICY,LS,JUDGE,JDIGEST=[constants[x] for x in ['J_SYSTEM','L_POLICY','LS','JUDGE','JDIGEST']]

def visible(g,layer):
 p=g['result'] if layer=='system' else g['validation'].get('parsed_model_response')
 if not isinstance(p,dict):return None,'UNPARSED_RAW_OUTPUT'
 if layer=='system':
  if p['answer_origin'] in {'ABSTAINED','VALIDATION_FAILED'}:return None,p['answer_origin']
  answer=p['final_answer']
 else:
  if p.get('answer_status')=='INSUFFICIENT_EVIDENCE':return None,'MODEL_ABSTENTION'
  answer=p.get('answer')
 if not isinstance(answer,str) or not answer.strip():return None,'EMPTY_VISIBLE_ANSWER'
 problem=content_problem(answer,g['question'])
 return (None,problem) if problem else (answer.strip(),None)

def chat(messages,key):
 payload={'model':JUDGE,'messages':messages,'stream':True,'format':LS,'keep_alive':'30m','options':{'temperature':0,'top_p':1,'seed':21021,'num_predict':512,'num_ctx':8192}}
 errors=[]
 for attempt in range(1,3):
  parts=[];trace=[];body={};error=None;t=time.perf_counter()
  try:
   with requests.post(OLLAMA+'/api/chat',json=payload,stream=True,timeout=(30,600)) as resp:
    resp.raise_for_status()
    for line in resp.iter_lines(chunk_size=1):
     if not line:continue
     ev=json.loads(line);trace.append({'elapsed_seconds':time.perf_counter()-t,'event':ev});parts.append((ev.get('message') or {}).get('content',''))
     if ev.get('error'):raise RuntimeError(ev['error'])
     if ev.get('done'):body=ev
   if not body.get('done'):raise ValueError('JUDGE_STREAM_MISSING_DONE')
   parsed=json.loads(''.join(parts));jsonschema.validate(parsed,LS)
  except Exception as exc:error=f'{type(exc).__name__}: {exc}';errors.append(error)
  append('logical_judge_raw_attempts.jsonl',{'input_key':key,'attempt':attempt,'payload':payload,'raw':''.join(parts),'trace':trace,'error':error,'model':JUDGE,'digest':JDIGEST,'wall_seconds':time.perf_counter()-t})
  if error is None:return {'status':'scored','scores':parsed,'errors':errors,'attempt_count':attempt,'judge_tag':JUDGE,'judge_digest':JDIGEST}
 return {'status':'judge_error','scores':None,'errors':errors,'attempt_count':2,'judge_tag':JUDGE,'judge_digest':JDIGEST}

def main():
 verify_freeze();gens=jl(W/'regression_results_200.jsonl');assert len(gens)==len({(g['question_id'],g['model_id']) for g in gens})==200
 refs={r['question_id']:r for r in jl(W/'verified_reference_answers_v3.jsonl')}
 assert sum(bool(r.get('logical_rubric')) for r in refs.values())==37 and sum(bool(r.get('expected_calculation')) for r in refs.values())==13
 tags=requests.get(OLLAMA+'/api/tags',timeout=30).json()['models'];assert next(m for m in tags if m['name']==JUDGE)['digest']==JDIGEST
 assert JDIGEST not in {g['model_digest'] for g in gens}
 for metric in ['arithmetic','logical']:
  fn=f'{metric}_regression_detailed.jsonl';old=jl(W/fn) if (W/fn).exists() else [];done={(x['question_id'],x['model_id'],x['answer_layer']) for x in old};cache={x['input_key']:x['evaluation'] for x in old if x.get('evaluation',{}).get('status')=='scored'}
  if metric=='logical':unload_all()
  for g in gens:
   ref=refs[g['question_id']];calc=ref.get('expected_calculation')
   if (metric=='arithmetic' and not calc) or (metric=='logical' and not ref.get('logical_rubric')):continue
   for layer in ['model','system']:
    if (g['question_id'],g['model_id'],layer) in done:continue
    answer,reason=visible(g,layer);row={'run_id':g['run_id'],'question_id':g['question_id'],'model_id':g['model_id'],'species':g['species'],'category':g['category'],'answer_layer':layer,'answer_origin':g['result']['answer_origin'],'source_group_ids':g['source_group_ids'],'rubric_sha256':ref['rubric_sha256'],'verification_level':'AUTO_SOURCE_VERIFIED; AI_ASSISTED; NOT_HUMAN_GOLD','verdict':'not_evaluable','reason':reason,'fixed_denominator_success':False,'validated_task_success':False}
    if answer and metric=='arithmetic':
     a,b=Decimal(calc['a']),Decimal(calc['b']);result={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert result==Decimal(calc['expected']);c=parse_arithmetic(answer,calc)
     row.update(formula=calc,decimal_reference_result=str(result),numeric_check=c,verdict=('correct' if c['correct'] else 'incorrect') if c['evaluable'] else 'not_evaluable',reason=c['reason'])
    elif answer:
     source=[{k:s.get(k) for k in ['source_id','source_version','exact_evidence_span','evidence_locator']} for s in ref['evidence_spans']]
     messages=[{'role':'system','content':J_SYSTEM},{'role':'user','content':L_POLICY+f"\nQuestion: {g['question']}\nSpecies: {g['species']}\nFrozen rubric: {json.dumps(ref['logical_rubric'],ensure_ascii=False)}\nSource: {json.dumps(source,ensure_ascii=False)}\nAnswer: {answer}"}];key=digest(messages);reused=key in cache;ev=cache[key] if reused else chat(messages,key)
     row.update(input_key=key,evaluation=ev,identical_input_cache_reuse=reused)
     if ev['status']=='scored':
      cache[key]=ev;s=ev['scores'];v=s['verdict']
      if v=='correct' and (not s['required_conditions_satisfied'] or s['material_contradictions']):v='not_evaluable';reason='JUDGE_INTERNAL_CONTRADICTION'
      else:reason=s['reason']
      row.update(verdict=v,reason=reason)
     else:row['reason']='JUDGE_ERROR'
    row['fixed_denominator_success']=row['verdict']=='correct'
    vs=g['result']['validation_status'];valid=g['result']['answer_status']=='ANSWERED_GROUNDED' and (layer=='system' or (g['result']['answer_origin']=='MODEL_GENERATED' and vs['raw_json_valid'] and vs['raw_citation_valid']))
    row['validated_task_success']=row['verdict']=='correct' and valid
    append(fn,row);print(metric,g['model_id'],g['question_id'],layer,row['verdict'],flush=True)
 if True:unload_all()
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
