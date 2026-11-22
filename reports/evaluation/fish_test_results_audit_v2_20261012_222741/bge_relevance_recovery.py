import collections, hashlib, json, math, re, statistics, urllib.request
from pathlib import Path
ROOT=Path.cwd(); RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'; OUT=ROOT/'reports/evaluation/fish_test_results_audit_v2_20261012_222741'
TAG='bge-m3:latest'; DIGEST='7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'; DIM=1024

def jl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def get(url, payload=None):
 data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
 req=urllib.request.Request('http://127.0.0.1:11434'+url,data=data,headers={'Content-Type':'application/json'} if data else {})
 with urllib.request.urlopen(req,timeout=180) as r:return json.loads(r.read())
def extract_answer(raw):
 m=re.search(r'"answer"\s*:\s*"',raw)
 if not m:return None
 start=m.end(); escaped=False
 for i in range(start,len(raw)):
  c=raw[i]
  if escaped: escaped=False; continue
  if c=='\\': escaped=True; continue
  if c=='"':
   try:return json.loads('"'+raw[start:i]+'"')
   except Exception:return None
 return None

tags=get('/api/tags'); found=next((x for x in tags.get('models',[]) if x.get('name')==TAG),None)
if not found or found.get('digest')!=DIGEST: raise RuntimeError(f'BGE identity mismatch: {found}')
qs=jl(RUN/'fish_test_questions_normalized.jsonl'); gs=jl(RUN/'generation_outputs.jsonl'); qmap={x['question_id']:x for x in qs}; rows=[]; usable=[]
for g in gs:
 qid,mid=g['question_id'],g['model_id']; parsed=g.get('parsed_output'); a=parsed.get('answer') if isinstance(parsed,dict) else None; method=None; failure=None
 if isinstance(a,str) and a.strip(): method='parsed_output.answer'
 elif isinstance(a,str): failure='empty_parsed_output.answer'
 else:
  raw=g.get('raw_output') or ''
  recovered=extract_answer(raw) if raw else None
  if isinstance(recovered,str) and recovered.strip(): a=recovered; method='raw_output.complete_answer_json_string_recovery'
  elif not raw.strip(): failure='empty_raw_output_and_no_parsed_answer'
  else: failure='no_complete_answer_json_string_in_unparseable_raw_output'
 if method:
  a=re.sub(r'(?is)<think>.*?</think>','',a).strip()
  if not a: failure='answer_empty_after_thinking_removal';method=None
  elif re.search(r'(?is)</?think>',a):failure='unmatched_inline_thinking_marker';method=None
 if not method:
  rows.append({'question_id':qid,'model_id':mid,'model_tag':g.get('model_tag'),'model_digest':g.get('model_digest'),'question_text':qmap[qid].get('question_text'),'generated_answer_text':None,'generated_answer_field':None,'answer_extraction_method':None,'schema_valid':g.get('schema_valid'),'embedding_model':TAG,'embedding_digest':DIGEST,'embedding_dimension':DIM,'normalization':'explicit L2 unit normalization; cosine is normalized dot product','bge_m3_answer_relevance_cosine':None,'status':'not_computable','failure_reason':failure,'context_or_gold_used':False})
 else:
  record={'question_id':qid,'model_id':mid,'model_tag':g.get('model_tag'),'model_digest':g.get('model_digest'),'question_text':qmap[qid].get('question_text'),'generated_answer_text':a,'generated_answer_field':method,'answer_extraction_method':method,'schema_valid':g.get('schema_valid'),'embedding_model':TAG,'embedding_digest':DIGEST,'embedding_dimension':DIM,'normalization':'explicit L2 unit normalization; cosine is normalized dot product','bge_m3_answer_relevance_cosine':None,'status':'pending','failure_reason':None,'context_or_gold_used':False}
  rows.append(record);usable.append((record,qmap[qid]['question_text'],a))
# Embed question/answer pairs in batches. No generator calls.
batch_pairs=24; errors=[]
for start in range(0,len(usable),batch_pairs):
 batch=usable[start:start+batch_pairs]; texts=[]
 for rec,q,a in batch:texts.extend([q,a])
 try:
  response=get('/api/embed',{'model':TAG,'input':texts,'truncate':False}); vecs=response.get('embeddings',[])
  if len(vecs)!=len(texts):raise ValueError(f'expected {len(texts)} vectors, got {len(vecs)}')
  for i,(rec,q,a) in enumerate(batch):
   vq,va=vecs[i*2],vecs[i*2+1]
   if len(vq)!=DIM or len(va)!=DIM:raise ValueError(f'wrong embedding dim {len(vq)}/{len(va)}')
   nq=math.sqrt(sum(float(z)*float(z) for z in vq)); na=math.sqrt(sum(float(z)*float(z) for z in va))
   if not nq or not na:raise ValueError('zero_norm_embedding')
   rec['question_vector_norm_before_normalization']=nq;rec['answer_vector_norm_before_normalization']=na
   rec['bge_m3_answer_relevance_cosine']=sum((float(x)/nq)*(float(y)/na) for x,y in zip(vq,va));rec['status']='scored'
 except Exception as exc:
  reason=f'{type(exc).__name__}: {exc}';errors.append({'batch_start':start,'error':reason})
  for rec,q,a in batch:rec['status']='not_computable';rec['failure_reason']=reason;rec['generated_answer_text']=None
(OUT/'bge_m3_answer_relevance.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
meta={'status':'completed' if not errors else 'completed_with_errors','model_tag':TAG,'model_digest':DIGEST,'runtime':'Ollama local /api/embed','input_pairs':len(usable),'input_texts':len(usable)*2,'scored_pairs':sum(r['status']=='scored' for r in rows),'not_computable':sum(r['status']!='scored' for r in rows),'dimension':DIM,'request_batch_pairs':batch_pairs,'truncate':False,'normalization':'explicit L2 normalization for each vector, followed by dot product','score':'raw cosine similarity, not transformed to 0-1','answer_extraction_counts':dict(collections.Counter(r.get('answer_extraction_method') for r in rows if r['status']=='scored')),'answer_extraction_policy':'Use parsed_output.answer when present; otherwise recover only a complete JSON string value for the answer key from malformed raw JSON. Never embed the entire raw response, thinking field, candidate answer, rubric, or Retrieval Context. Remove complete inline <think> blocks and exclude unmatched thinking markers.','unparseable_raw_outputs_with_recovered_complete_answer':sum(r.get('answer_extraction_method')=='raw_output.complete_answer_json_string_recovery' and r['status']=='scored' for r in rows),'embedding_errors':errors}
(OUT/'bge_m3_embedding_method.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Refresh per-model BGE summaries.
mm=json.loads((OUT/'model_metrics_v2.json').read_text(encoding='utf-8'))
for mid in ['M1','M2','M3','M4']:
 vals=[r['bge_m3_answer_relevance_cosine'] for r in rows if r['model_id']==mid and isinstance(r['bge_m3_answer_relevance_cosine'],(int,float))]
 mm['models'][mid]['bge_m3_answer_relevance_cosine']={'n':len(vals),'mean':statistics.mean(vals) if vals else None}
(OUT/'model_metrics_v2.json').write_text(json.dumps(mm,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Refresh paired sample comparison BGE arm only.
pair_path=OUT/'paired_sample_comparison.json'; pair=json.loads(pair_path.read_text(encoding='utf-8')); by={(r['question_id'],r['model_id']):r for r in rows}; mids=['M1','M2','M3','M4']; qids=[q['question_id'] for q in qs]
allstats={}; values_by_mid={}
for mid in mids:
 vs=[by[(qid,mid)]['bge_m3_answer_relevance_cosine'] for qid in qids if (qid,mid) in by and isinstance(by[(qid,mid)]['bge_m3_answer_relevance_cosine'],(int,float))]
 allstats[mid]={'n':len(vs),'mean':statistics.mean(vs) if vs else None};values_by_mid[mid]=vs
common=[qid for qid in qids if all(isinstance(by[(qid,mid)]['bge_m3_answer_relevance_cosine'],(int,float)) for mid in mids)]
pairedmeans={mid:statistics.mean([by[(qid,mid)]['bge_m3_answer_relevance_cosine'] for qid in common]) for mid in mids}
pair['all_available_samples']['bge_m3_answer_relevance_cosine']=allstats
pair['paired_common_samples']['bge_m3_answer_relevance_cosine']={'n':len(common),'question_ids':common,'means':pairedmeans}
pair['pairwise_differences']['bge_m3_answer_relevance_cosine']=[{'model_a':a,'model_b':bmid,'difference':f'{a} minus {bmid}','n':len(common),'mean_difference':pairedmeans[a]-pairedmeans[bmid]} for i,a in enumerate(mids) for bmid in mids[i+1:]]
pair_path.write_text(json.dumps(pair,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Refresh exact-stem sensitivity BGE metric.
sens_path=OUT/'exact_stem_sensitivity.json';sens=json.loads(sens_path.read_text(encoding='utf-8'));groups=collections.OrderedDict()
for q in qs:groups.setdefault(' '.join(q['question_text'].split()),[]).append(q)
per={mid:[] for mid in mids};common_groups=[]
for stem,items in groups.items():
 gm={}
 for mid in mids:
  vals=[]
  for q in items:
   v=by[(q['question_id'],mid)]['bge_m3_answer_relevance_cosine']
   if isinstance(v,(int,float)):vals.append(float(v))
  if vals:gm[mid]=statistics.mean(vals);per[mid].append(gm[mid])
 if len(gm)==4:common_groups.append(gm)
sens['metrics']['bge_m3_cosine']={'all_exact_stem_groups':{mid:{'n':len(per[mid]),'mean':statistics.mean(per[mid]) if per[mid] else None} for mid in mids},'paired_common_exact_stem_groups':{'n':len(common_groups),'means':{mid:statistics.mean([x[mid] for x in common_groups]) if common_groups else None for mid in mids}}}
sens_path.write_text(json.dumps(sens,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Add distinction to reconciliation without rewriting historical counts.
rp=OUT/'raw_run_reconciliation.json';rec=json.loads(rp.read_text(encoding='utf-8'));rec['bge_m3_answer_text_usable_records']=len(usable);rec['bge_m3_parsed_answer_records']=sum(r.get('answer_extraction_method')=='parsed_output.answer' and r['status']=='scored' for r in rows);rec['bge_m3_recovered_complete_answer_json_strings']=meta['unparseable_raw_outputs_with_recovered_complete_answer'];rec['bge_m3_not_computable']=meta['not_computable'];rp.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'input_pairs':len(usable),'scored':meta['scored_pairs'],'not_computable':meta['not_computable'],'extraction_counts':meta['answer_extraction_counts'],'model_means':{mid:mm['models'][mid]['bge_m3_answer_relevance_cosine'] for mid in mids},'paired_common_n':len(common)},ensure_ascii=False))
