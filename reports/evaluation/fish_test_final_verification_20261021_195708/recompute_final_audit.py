"""Read-only recomputation of the frozen run. No inference or corpus mutation."""
from pathlib import Path
import json,hashlib,statistics,collections,itertools,math,sys,csv,datetime,platform,ast
from decimal import Decimal
import openpyxl,jsonschema
W=Path(__file__).resolve().parent
R=W.parents[2]
I=R/'reports/evaluation/fish_test_corpus_v3_frozen_run_20261021_133102'
MIDS=['M1','M2','M3','M4']; LAYERS=['model','system']
KEYS=['faithfulness','judge_answer_relevance','bge_m3_cosine','structured_ifr','ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib','logical_accuracy','arithmetic_accuracy']
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def j(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def jl(p):return [json.loads(s) for s in Path(p).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def wr(n,v):(W/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def wl(n,rows):(W/n).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in rows),encoding='utf-8')
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def stat(vals):
 v=[float(x) for x in vals if x is not None and isinstance(x,(int,float)) and math.isfinite(x)]
 return dict(n=len(v),mean=statistics.mean(v) if v else None,median=statistics.median(v) if v else None,sd=statistics.stdev(v) if len(v)>1 else None,min=min(v) if v else None,max=max(v) if v else None)
def acc(rows):
 c=collections.Counter(x['verdict'] for x in rows);n=c['correct']+c['incorrect']
 return dict(eligible_n=len(rows),n=n,correct=c['correct'],incorrect=c['incorrect'],not_evaluable=c['not_evaluable'],accuracy=c['correct']/n if n else None,correct_per_eligible=c['correct']/len(rows) if rows else None)
def snapshot_input():
 rows=[]
 def visit(p):
  for c in sorted(p.iterdir()):
   if c.is_symlink() or (hasattr(c,'is_junction') and c.is_junction()):continue
   if c.is_dir():visit(c)
   elif c.is_file():rows.append({'path':str(c),'sha256':sha(c),'bytes':c.stat().st_size})
 visit(I);return rows
def protected():
 p=R/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json';m=j(p);rows=[]
 for x in m['files']:
  a=sha(R/x['path']) if (R/x['path']).is_file() else None;rows.append({**x,'actual_sha256':a,'unchanged':a==x['sha256']})
 return {'manifest':str(p),'total':len(rows),'unchanged':sum(x['unchanged'] for x in rows),'files':rows}
def main():
 before=W/'input_file_hashes_before.json'
 if not before.exists():wr(before.name,{'at':datetime.datetime.now().astimezone().isoformat(),'files':snapshot_input(),'excluded':'node_modules junction points to bundled dependencies; no research data excluded'})
 b=protected();wr('protected_baseline_before.json',b);assert b['total']==b['unchanged']==636
 manifest=j(I/'frozen_evaluation_manifest.json');frozen=[{'path':x['path'],'expected':x['sha256'],'actual':sha(I/x['path'])} for x in manifest['frozen_files']];assert all(x['actual']==x['expected'] for x in frozen)
 qs=jl(I/'questions_original_180.jsonl');qm={q['question_id']:q for q in qs};ctx={x['question_id']:x for x in jl(I/'frozen_corpus_and_contexts_180.jsonl')};refs={x['question_id']:x for x in jl(I/'verified_reference_answers_v3.jsonl')};av={x['question_id']:x for x in jl(I/'corpus_evidence_availability_180.jsonl')}
 gs=jl(I/'generator_final_results_720.jsonl');ats=jl(I/'generator_raw_attempts_720.jsonl');gm={(g['question_id'],g['model_id']):g for g in gs};am={x['attempt_id']:x for x in ats};quality=jl(I/'judge_quality_detailed.jsonl');bge=jl(I/'bge_relevance_detailed.jsonl');lr=jl(I/'logical_accuracy_detailed.jsonl');ar=jl(I/'arithmetic_accuracy_detailed.jsonl')
 qa={(x['question_id'],x['model_id'],x['answer_layer']):x for x in quality};bg={(x['question_id'],x['model_id'],x['answer_layer']):x for x in bge};lo={(x['question_id'],x['model_id'],x['answer_layer']):x for x in lr};aa={(x['question_id'],x['model_id'],x['answer_layer']):x for x in ar};content={(x['question_id'],x['model_id'],x['answer_layer']):x for x in jl(I/'response_content_audit_1440.jsonl')}
 assert len(qs)==len(qm)==len(ctx)==len(refs)==180 and len(gs)==len(gm)==720 and len(ats)==720
 assert len({q['question_text'] for q in qs})==175
 assert len(quality)==len(qa)==len(bge)==len(bg)==1440 and len(lr)==296 and len(ar)==104
 # Original workbooks are opened read-only; do not import their duplicated test-data sheet.
 books={};workbook_audit=[]
 for q in qs:
  p=R/'fish test'/q['source_workbook']
  if p.name not in books:
   assert sha(p)==q['source_workbook_sha256'];books[p.name]=openpyxl.load_workbook(p,read_only=True,data_only=True)
  cells=next(books[p.name]['題目庫'].iter_rows(min_row=q['question_bank_excel_row'],max_row=q['question_bank_excel_row'],values_only=True))
  assert cells[0]==q['original_question_id'] and cells[6]==q['question_text']
  workbook_audit.append({'question_id':q['question_id'],'file':str(p),'sheet':'題目庫','row':q['question_bank_excel_row'],'question_and_id_match':True,'workbook_sha256':q['source_workbook_sha256']})
 for bk in books.values():bk.close()
 wl('original_question_alignment_180.jsonl',workbook_audit)
 checks=[];promptnorm={};rawparsed={}
 for g in gs:
  qid,mid=g['question_id'],g['model_id'];q=qm[qid];c=ctx[qid]
  assert g['run_id']==manifest['run_id'] and g['question']==q['question_text']==c['question']
  assert g['species']==q['species_chinese']==c['species'] and g['category']==q['inferred_category']==c['category']
  assert g['model_digest']==manifest['models'][mid]['digest'] and g['model_tag']==manifest['models'][mid]['tag']
  assert g['context_digest']==c['context_digest']==digest(c['top5']) and g['context_ids']==[x['chunk_id'] for x in c['top5']]
  assert g['context_count']==len(c['top5']) and g['corpus_sha256']==manifest['corpus']['database_sha256'] and g['prompt_version']==manifest['prompt_version']
  payload=j(g['prompt_file']);assert digest(payload)==g['prompt_sha256'];assert payload['options']==manifest['generation_options'] and payload['system']==manifest['system']
  pn=digest({k:payload[k] for k in ['system','prompt','format','options']});promptnorm.setdefault(qid,set()).add(pn)
  a=am[g['attempt_id']];assert a['raw_model_response']==g['raw_model_response'] and a['api_completed']==g['api_completed']
  valid=False;p=None
  try:p=json.loads(g['raw_model_response']);jsonschema.validate(p,manifest['schema']);valid=True
  except (json.JSONDecodeError,jsonschema.ValidationError):pass
  assert valid==g['raw_model_structure_valid'];rawparsed[(qid,mid)]=p
  eng=g['engine_metrics'];tps=eng['eval_count']/(eng['eval_duration']/1e9) if eng.get('eval_count') is not None and eng.get('eval_duration') else None
  assert (tps is None and g['tps'] is None) or abs(tps-g['tps'])<1e-10
  tr=jl(g['stream_trace_file']);first=next((x['elapsed_seconds'] for x in tr if x['event'].get('response')),None);assert first==g['ttft_visible_content_seconds']
  if g['answer_origin']=='MODEL_GENERATED':assert valid and p['abstained'] is False and g['raw_citation_validation']['status']=='PASS'
  if not g['final_response']['abstained']:assert g['evidence_decision']['state']=='EVIDENCE_SUFFICIENT' and g['final_citation_validation']['status']=='PASS'
  checks.append({'question_id':qid,'model_id':mid,'run_id':g['run_id'],'source_row':gs.index(g)+1,'question_match':True,'model_digest':g['model_digest'],'context_digest':g['context_digest'],'prompt_sha256':g['prompt_sha256'],'prompt_version':g['prompt_version'],'raw_schema_valid':valid,'raw_citation_status':g['raw_citation_validation']['status'],'answer_origin':g['answer_origin'],'raw_declared_abstention':p.get('abstained') if isinstance(p,dict) else None,'final_abstained':g['final_response']['abstained'],'quality_valid':qa[(qid,mid,'model')]['faithfulness'] is not None})
 assert all(len(s)==1 for s in promptnorm.values())
 assert manifest['models']['M3']['details']['family']=='llama'
 wl('record_integrity_audit_720.jsonl',checks)
 # Bind every scored quality/Logical item to the exact saved independent Judge request.
 constants={}
 for node in ast.parse((I/'score_frozen_run.py').read_text(encoding='utf-8')).body:
  if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant):
   for target in node.targets:
    if isinstance(target,ast.Name):constants[target.id]=node.value.value
 calls=jl(I/'judge_raw_attempts.jsonl');callmap=collections.defaultdict(list)
 for call in calls:
  assert digest(call['payload']['messages'])==call['key']
  assert call['digest']==constants['JDIGEST'] and call['payload']['model']==constants['JUDGE']
  callmap[(call['kind'],call['key'])].append(call)
 assert constants['JDIGEST'] not in {s['digest'] for s in manifest['models'].values()}
 judge_bindings=[]
 for kind,rows in [('QUALITY',quality),('LOGICAL',lr)]:
  for row in rows:
   if not row.get('evaluation'):continue
   g=gm[(row['question_id'],row['model_id'])];p=rawparsed[(g['question_id'],g['model_id'])] if row['answer_layer']=='model' else g['final_response'];assert isinstance(p,dict) and p.get('abstained') is False and isinstance(p.get('answer'),str)
   answer=p['answer'].strip()
   if kind=='QUALITY':
    ct='\n\n'.join(f"[{c['chunk_id']}] {c['source_version']} {c['exact_locator']}\n{c['text']}" for c in ctx[g['question_id']]['top5'])
    user=constants['J_POLICY']+f"\nQuestion: {g['question']}\nContext:\n{ct}\nAnswer:\n{answer}"
   else:
    ref=refs[g['question_id']];source=[{k:s.get(k) for k in ['source_id','source_version','exact_evidence_span','evidence_locator']} for s in ref['evidence_spans']]
    user=constants['L_POLICY']+f"\nQuestion: {g['question']}\nSpecies: {g['species']}\nFrozen rubric: {json.dumps(ref['logical_rubric'],ensure_ascii=False)}\nSource: {json.dumps(source,ensure_ascii=False)}\nAnswer: {answer}"
   expected=digest([{'role':'system','content':constants['J_SYSTEM']},{'role':'user','content':user}]);assert row['input_key']==expected
   saved=callmap[(kind,expected)];assert saved and any(not c['error'] for c in saved)
   assert row['evaluation']['judge_digest']==constants['JDIGEST']
   judge_bindings.append({'kind':kind,'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':row['answer_layer'],'prompt_sha256':expected,'saved_attempts':len(saved),'exact_input_binding_passed':True,'cached_identical_input':row.get('identical_input_cache_reuse',False)})
 wl('judge_input_binding_audit.jsonl',judge_bindings)
 # Recompute only summaries of stored scores, never call or rescore a model.
 facts=[]
 for g in gs:
  for layer in LAYERS:
   k=(g['question_id'],g['model_id'],layer);qrow=qa[k];brow=bg[k];l=lo.get(k);a=aa.get(k);h=g['hardware']
   if qrow['faithfulness'] is not None:
    assert qrow['evaluation']['scores']['faithfulness']==qrow['faithfulness'] and qrow['evaluation']['scores']['answer_relevance']==qrow['judge_answer_relevance']
   if a:
    f=a['formula'];x,y=Decimal(f['a']),Decimal(f['b']);n={'multiply':lambda:x*y,'divide':lambda:x/y,'subtract':lambda:x-y}[f['operation']]();assert n==Decimal(f['expected'])==Decimal(a['decimal_reference_result'])
    if a['verdict'] in ['correct','incorrect']:assert (abs(Decimal(a['parsed_numeric_value'])-n)<=Decimal(f['tolerance']))==(a['verdict']=='correct')
   facts.append({'question_id':g['question_id'],'model_id':g['model_id'],'answer_layer':layer,'species':g['species'],'category':g['category'],'answer_origin':g['answer_origin'],'evidence_gap':av[g['question_id']]['gap_classification'],'source_group_ids':av[g['question_id']]['original_record_group_keys'],'faithfulness':qrow['faithfulness'],'judge_answer_relevance':qrow['judge_answer_relevance'],'bge_m3_cosine':brow['cosine'],'structured_ifr':int(g['raw_model_structure_valid']),'ttft_seconds':g['ttft_visible_content_seconds'],'tps':g['tps'],'peak_system_ram_gib':h['peak_system_ram_bytes']/2**30 if h['peak_system_ram_bytes'] is not None else None,'peak_dedicated_vram_gib':h['peak_dedicated_vram_bytes']/2**30 if h['peak_dedicated_vram_bytes'] is not None else None,'logical_accuracy':1 if l and l['verdict']=='correct' else 0 if l and l['verdict']=='incorrect' else None,'arithmetic_accuracy':1 if a and a['verdict']=='correct' else 0 if a and a['verdict']=='incorrect' else None,'content_status':content[k]['content_status']})
 wl('metrics_recomputed_1440.jsonl',facts)
 old=j(I/'evaluation_metrics_11.json');allstats={l:{m:{k:stat([x[k] for x in facts if x['answer_layer']==l and x['model_id']==m]) for k in KEYS} for m in MIDS} for l in LAYERS};paired={};recon=[]
 for l in LAYERS:
  paired[l]={}
  for metric in KEYS:
   sets=[{r['question_id'] for r in facts if r['answer_layer']==l and r['model_id']==m and r[metric] is not None} for m in MIDS];common=set.intersection(*sets)
   paired[l][metric]={'n':len(common),'question_ids':sorted(common),'models':{m:stat([r[metric] for r in facts if r['answer_layer']==l and r['model_id']==m and r['question_id'] in common]) for m in MIDS}}
   for m in MIDS:
    a,b=allstats[l][m][metric],old['all_available_samples'][l][m][metric];assert a['n']==b['n'] and (a['mean']==b['mean'] or abs(a['mean']-b['mean'])<1e-12)
    p=old['four_model_paired_samples'][l][metric];assert set(p['question_ids'])==common
    recon.append({'layer':l,'model':m,'metric':metric,'n':a['n'],'recomputed_mean':a['mean'],'frozen_mean':b['mean'],'absolute_difference':0 if a['mean'] is None else abs(a['mean']-b['mean']),'match':True})
 assert paired['model']['logical_accuracy']['n']==27 and paired['model']['arithmetic_accuracy']['n']==7
 wl('metric_reconciliation_80.jsonl',recon)
 # Audit why source-agnostic response quality N exceeds final citation-gated answers.
 flows=[];cross=[];judge_reasons=[]
 for m in MIDS:
  sel=[g for g in gs if g['model_id']==m];scored=[g for g in sel if qa[(g['question_id'],m,'model')]['faithfulness'] is not None]
  origins=collections.Counter(g['answer_origin'] for g in sel)
  row={'model_id':m,'total':len(sel),'api_completed':sum(g['api_completed'] for g in sel),'raw_schema_valid':sum(g['raw_model_structure_valid'] for g in sel),'raw_model_declared_abstention':sum(isinstance(rawparsed[(g['question_id'],m)],dict) and rawparsed[(g['question_id'],m)].get('abstained') is True for g in sel),'raw_quality_valid_n':len(scored),'raw_bge_valid_n':allstats['model'][m]['bge_m3_cosine']['n'],'raw_citation_pass_among_judge_valid':sum(g['raw_citation_validation']['status']=='PASS' for g in scored),'final_model_generated':origins['MODEL_GENERATED'],'deterministic_extraction':origins['DETERMINISTIC_EVIDENCE_EXTRACTION'],'system_abstained':origins['ABSTAINED'],'validation_failed':origins['VALIDATION_FAILED'],'system_nonabstained':sum(not g['final_response']['abstained'] for g in sel),'system_quality_valid_n':allstats['system'][m]['faithfulness']['n'],'system_content_nonanswers':sum(content[(g['question_id'],m,'system')]['content_status'] in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'} for g in sel)}
  assert row['raw_quality_valid_n']==sum(qa[(g['question_id'],m,'model')]['judge_answer_relevance'] is not None for g in sel)
  flows.append(row)
  for origin in ['MODEL_GENERATED','DETERMINISTIC_EVIDENCE_EXTRACTION','ABSTAINED','VALIDATION_FAILED']:
   sub=[g for g in scored if g['answer_origin']==origin];cross.append({'model_id':m,'final_answer_origin':origin,'judge_valid_raw_n':len(sub),'raw_citation_fail_n':sum(g['raw_citation_validation']['status']=='FAIL' for g in sub),'insufficient_evidence_state_n':sum(g['evidence_decision']['state']!='EVIDENCE_SUFFICIENT' for g in sub),'note':'Counts describe different stages, not duplicate or automatically invalid Judge observations.'})
  for g in sel:
   jq=qa[(g['question_id'],m,'model')];judge_reasons.append({'question_id':g['question_id'],'model_id':m,'judge_score_valid':jq['faithfulness'] is not None,'raw_citation_status':g['raw_citation_validation']['status'],'system_origin':g['answer_origin'],'evidence_state':g['evidence_decision']['state'],'quality_missing_reason':jq.get('reason'),'judge_input':'json.loads(raw_model_response)[answer], only nonempty string and abstained is exactly false; no citation gate prerequisite','source_jsonl':'judge_quality_detailed.jsonl'})
 wr('judge_denominator_explanation.json',{'flow':flows,'cross_tab':cross,'policy':'Judge scores visible non-abstained raw answer before system evidence/citation enforcement. System may block that same answer, or replace it with deterministic extraction. These are intentionally different populations.','scoring_quality_is_not_professional_truth':True});wl('judge_population_audit_720.jsonl',judge_reasons)
 # Preserve five user-highlighted final-system no-answer cases together with the v1 values.
 oldlo={(x['question_id'],x['model_id'],x['answer_layer']):x for x in jl(I/'logical_accuracy_detailed_frozen_parser_v1.jsonl')};oldar={(x['question_id'],x['model_id'],x['answer_layer']):x for x in jl(I/'arithmetic_accuracy_detailed_frozen_parser_v1.jsonl')};oldbg={(x['question_id'],x['model_id'],x['answer_layer']):x for x in jl(I/'bge_relevance_detailed_frozen_parser_v1.jsonl')}
 special=[]
 keys={(x['question_id'],x['model_id']) for x in content.values() if x['answer_layer']=='system' and x['content_status'] in {'QUESTION_ECHO_NO_ANSWER','INCOMPLETE_ANTECEDENT_NO_ANSWER'}}
 for qid,m in sorted(keys):
  g=gm[(qid,m)];r={'question_id':qid,'model_id':m,'question':g['question'],'raw_model_response':g['raw_model_response'],'final_response':g['final_response'],'origin_unchanged':g['answer_origin'],'per_layer':{}}
  for layer in LAYERS:
   k=(qid,m,layer);r['per_layer'][layer]={'content':content[k],'bge_before':oldbg[k],'bge_after':bg[k],'logical_before':oldlo.get(k),'logical_after':lo.get(k),'arithmetic_before':oldar.get(k),'arithmetic_after':aa.get(k),'quality_scores_unchanged':qa[k]}
  special.append(r)
 assert collections.Counter(x['model_id'] for x in special)=={'M2':1,'M3':4};wl('incomplete_and_echo_cases_preserved_5.jsonl',special)
 # Exact same question IDs for all four models; do not pool unmatched rows.
 prows=[];pstats=[];pairdiff=[];speciespaired=[]
 for name,records in [('Logical',lr),('Arithmetic',ar)]:
  metric=name.lower()+'_accuracy';common=paired['model'][metric]['question_ids']
  for qid in common:
   ref=refs[qid];row={'metric':name,'question_id':qid,'species':ctx[qid]['species'],'category':ctx[qid]['category'],'original_question':ctx[qid]['question'],'reference_answer':ref.get('reference_answer'),'required_elements':ref.get('required_answer_elements'),'source_group_ids':av[qid]['original_record_group_keys'],'evidence_spans':ref['evidence_spans'],'rubric_sha256':ref['rubric_sha256'],'logical_rubric':ref.get('logical_rubric'),'arithmetic_formula':ref.get('expected_calculation'),'models':{},'verification':'AUTO_SOURCE_VERIFIED; NOT_HUMAN_GOLD'}
   for m in MIDS:
    r=next(x for x in records if x['question_id']==qid and x['model_id']==m and x['answer_layer']=='model');g=gm[(qid,m)];assert r['verdict'] in {'correct','incorrect'};row['models'][m]={'verdict':r['verdict'],'correct':int(r['verdict']=='correct'),'reason':r['reason'],'observable_raw_answer':(rawparsed[(qid,m)] or {}).get('answer'),'final_system_origin':g['answer_origin'],'judge_evaluation':r.get('evaluation'),'parsed_numeric_value':r.get('parsed_numeric_value'),'reference_numeric_value':r.get('decimal_reference_result')}
   prows.append(row)
  for m in MIDS:
   sub=[x for x in records if x['model_id']==m and x['answer_layer']=='model'];pstats.append({'metric':name,'model_id':m,'view':'all_available','stats':acc(sub)});pstats.append({'metric':name,'model_id':m,'view':'four_model_common','stats':acc([x for x in sub if x['question_id'] in common])})
  for a,b in itertools.combinations(MIDS,2):
   sub=[x for x in prows if x['metric']==name];v=collections.Counter((x['models'][a]['correct'],x['models'][b]['correct']) for x in sub);pairdiff.append({'metric':name,'model_a':a,'model_b':b,'n':len(sub),'both_correct':v[(1,1)],'both_incorrect':v[(0,0)],'a_only_correct':v[(1,0)],'b_only_correct':v[(0,1)],'accuracy_difference_a_minus_b':(v[(1,0)]-v[(0,1)])/len(sub) if sub else None,'inference':'DESCRIPTIVE_ONLY; no significance test or independence claim'})
  for species in sorted({c['species'] for c in ctx.values()}):
   for m in MIDS:
    sub=[x for x in prows if x['metric']==name and x['species']==species];speciespaired.append({'metric':name,'species':species,'model_id':m,'n':len(sub),'correct':sum(x['models'][m]['correct'] for x in sub),'incorrect':sum(not x['models'][m]['correct'] for x in sub),'accuracy':statistics.mean(x['models'][m]['correct'] for x in sub) if sub else None})
 wl('paired_question_comparison_34.jsonl',prows);wr('paired_analysis.json',{'summary':pstats,'pairwise_discordance':pairdiff,'species_distribution':speciespaired,'fixed_common_question_ids':{x:paired['model'][x.lower()+'_accuracy']['question_ids'] for x in ['Logical','Arithmetic']},'no_hypothesis_test':True})
 # Source group and source-file dependence; overlapping membership is preserved.
 full={qid for qid,r in refs.items() if r.get('logical_rubric') or r.get('expected_calculation')};groupqs=collections.defaultdict(set);fileqs=collections.defaultdict(set)
 for qid in full:
  for g in av[qid]['original_record_group_keys']:groupqs[g].add(qid)
  for s in refs[qid]['evidence_spans']:fileqs[s['source_sha256']].add(qid)
 assert len(full)==50 and len(groupqs)==10 and len(fileqs)==3
 groups=[];filegroups=[]
 for typ,groupset,target in [('record_or_page',groupqs,groups),('original_file',fileqs,filegroups)]:
  for group,qset in sorted(groupset.items()):
   for metric,recs in [('Logical',lr),('Arithmetic',ar)]:
    for layer in LAYERS:
     for m in MIDS:
      base=[x for x in recs if x['answer_layer']==layer and x['model_id']==m];inside=[x for x in base if x['question_id'] in qset];outside=[x for x in base if x['question_id'] not in qset];a,ib,ob=acc(base),acc(inside),acc(outside)
      target.append({'source_type':typ,'source_group':group,'question_ids':sorted(qset),'source_question_n':len(qset),'source_question_share':len(qset)/50,'metric':metric,'answer_layer':layer,'model_id':m,'within_group':ib,'without_group':ob,'all_eligible':a,'all_minus_without_accuracy':a['accuracy']-ob['accuracy'] if a['accuracy'] is not None and ob['accuracy'] is not None else None,'not_causal_effect':True})
 remaining=set(full);components=[]
 while remaining:
  comp={min(remaining)};changed=True
  while changed:
   oldn=len(comp)
   for qset in groupqs.values():
    if comp&qset:comp|=qset
   changed=len(comp)!=oldn
  remaining-=comp;components.append(sorted(comp))
 wl('source_group_influence.jsonl',groups);wl('source_file_influence.jsonl',filegroups)
 wr('source_dependency_summary.json',{'qualified_questions':50,'source_group_n':10,'source_file_n':3,'group_memberships':{g:sorted(v) for g,v in groupqs.items()},'file_memberships':{g:sorted(v) for g,v in fileqs.items()},'overlap_membership_count':sum(len(v) for v in groupqs.values()),'record_page_connected_components':components,'record_page_component_n':len(components),'max_group_question_share':max(len(v) for v in groupqs.values())/50,'human_gold_n':0,'limits':'Record/PDF page groups share three original files. Leave-one-group-out describes composition sensitivity, not causal influence or independent expert evidence. Existing group bootstrap is exploratory and not recomputed as a formal confidence statement.'})
 # Dataset and species summaries, keeping nonapplicable and N/A distinct from 0.
 breakdown={}
 for dim in ['species','category','evidence_gap','answer_origin']:
  breakdown[dim]={v:{l:{m:{k:stat([x[k] for x in facts if x[dim]==v and x['answer_layer']==l and x['model_id']==m]) for k in KEYS} for m in MIDS} for l in LAYERS} for v in sorted({x[dim] for x in facts})}
 wr('species_category_evidence_outcome_statistics.json',breakdown)
 coverage=[]
 for s in sorted({c['species'] for c in ctx.values()}):
  qset={k for k,c in ctx.items() if c['species']==s};coverage.append({'species':s,'question_n':len(qset),'full_support_n':len(qset&full),'logical_qualified_n':sum(bool(refs[qid].get('logical_rubric')) for qid in qset),'arithmetic_qualified_n':sum(bool(refs[qid].get('expected_calculation')) for qid in qset),'any_context_n':sum(bool(ctx[qid]['top5']) for qid in qset),'full_top5_n':sum(len(ctx[qid]['top5'])==5 for qid in qset)})
 p5=jl(I/'context_precision_detailed.jsonl');pv=[p['p_at_5'] for p in p5 if p['p_at_5'] is not None]
 assert len(pv)==12 and abs(stat(pv)['mean']-.3)<1e-12
 formulas={
 'faithfulness':'Independent Mistral NeMo 0–1 supported observable claims judgment against retrieved Context. Preserve score; not a deterministic expert accuracy.',
 'judge_answer_relevance':'Independent Mistral NeMo 0–1 question addressing judgment; separate from embedding and professional accuracy.',
 'bge_m3_cosine':'dot(q,a)/(L2(q)*L2(a)); original BGE-M3 1024 scores, no Gold/Context/thinking. Offline aggregate recomputation only; embeddings not rerun.',
 'structured_ifr':'N(raw model JSON passes frozen JSON Schema)/180. System repair does not change raw validity.',
 'ttft_seconds':'Saved first nonempty response stream elapsed_seconds; timer begins in request wrapper before sampler startup. Not semantic answer latency.',
 'tps':'Ollama eval_count/(eval_duration/1e9); duration in nanoseconds; engine token counts may include reasoning.',
 'peak_system_ram_gib':'Mean over calls of peak sampled system used RAM bytes/2^30, sampling interval 0.5 s; not model process memory.',
 'peak_dedicated_vram_gib':'Mean over calls of peak sampled GPU dedicated used bytes/2^30; nvidia-smi fallback valid despite pynvml import warning.',
 'logical_accuracy':'N_correct/(N_correct+N_incorrect) among 37 source-qualified questions, excluding refusals/uninterpretable as N/A; frozen rubric + independent AI Judge.',
 'arithmetic_accuracy':'N_correct/(N_correct+N_incorrect) among 13 applied arithmetic questions; Decimal reference and unit parser, tolerance frozen. No FCR/SGR/bFCR protocol qualification.',
 'context_precision_at_5':'Count binary Relevant labels/5; only full five contexts and reliable labels. Mean only over 12 purposively reviewed questions, not all180.'}
 wr('metric_definition_and_denominator_audit_11.json',{'definitions':formulas,'all_available':allstats,'four_model_paired':paired,'p5':{'summary':stat(pv),'species':{s:stat([p['p_at_5'] for p in p5 if p['species']==s]) for s in sorted({p['species'] for p in p5})}},'quality_to_citation_population':flows,'human_gold_n':0,'shared_gpu_memory':None,'memory_pressure_score':None,'weighted_total':None,'winner':None,'model_and_system_efficiency_same_underlying_call':True})
 # Read-only verification of the already delivered workbook, no editing of any historical file.
 bk=openpyxl.load_workbook(I/'fish_test_evaluation_v3.xlsx',read_only=True,data_only=True);excelchecks=[]
 for mi,m in enumerate(MIDS):
  for ki,k in enumerate(KEYS):
   cell=bk['Dashboard'].cell(ki+6,mi*2+2).value;n=bk['Dashboard'].cell(ki+6,mi*2+3).value;s=allstats['model'][m][k];assert n==s['n'] and abs(cell-s['mean'])<1e-10;excelchecks.append({'model':m,'metric':k,'mean_matches':True,'n_matches':True})
 bk.close();wr('historical_excel_readonly_verification.json',{'file':str(I/'fish_test_evaluation_v3.xlsx'),'sha256':sha(I/'fish_test_evaluation_v3.xlsx'),'checks':excelchecks,'modified':False})
 # A literal taxonomy mismatch in an observed Judge explanation is a warning, not an automatic re-score.
 warning=[{'question_id':x['question_id'],'model_id':x['model_id'],'answer_layer':x['answer_layer'],'rationale':x['evaluation']['scores'].get('rationale'),'warning':'Judge rationale includes Goonch catfish while question says 吳郭魚; recorded wording is inconsistent; scores retained without semantic rejudging.'} for x in quality if 'Goonch' in str((x.get('evaluation') or {}).get('scores',{}))]
 wr('judge_rationale_observed_warnings.json',{'literal_warning_count':len(warning),'rows':warning,'scores_changed':False,'not_exhaustive_semantic_audit':True})
 report={'run_id':manifest['run_id'],'audit_workspace':str(W),'input_workspace':str(I),'question_n':180,'canonical_n':len(gs),'attempt_n':len(ats),'per_model':{m:sum(g['model_id']==m for g in gs) for m in MIDS},'api_completed':sum(g['api_completed'] for g in gs),'frozen_files_verified':frozen,'question_digest_context_prompt_checks_passed':720,'all_qid_model_pairs_unique':True,'question_species_category_distribution':coverage,'category_n':dict(collections.Counter(c['category'] for c in ctx.values())),'gaps':dict(collections.Counter(v['gap_classification'] for v in av.values())),'source_groups':10,'source_files':3,'quality_counts_explained':True,'scores_changed':False,'generator_calls_performed':0,'corpus_modified':False,'raw_schema_counts':{x['model_id']:x['raw_schema_valid'] for x in flows},'metric_summary':allstats,'paired_accuracy_summary':pstats,'p5':stat(pv),'five_special_cases_preserved':True,'human_gold':0,'historical_tests':j(I/'repository_pytest_results.json'),'historical_e2e':j(I/'pre_run_e2e_validation.json'),'no_new_model_e2e_run':True,'model_weight_full_bytes_rehashed':False}
 wr('final_statistical_verification.json',report)
 wr('recomputed_data_package.json',{'audit':report,'models':manifest['models'],'corpus':manifest['corpus'],'retrieval':manifest['retrieval'],'generation_options':manifest['generation_options'],'hardware':j(I/'hardware_and_runtime.json'),'allstats':allstats,'paired':paired,'paired_summary':pstats,'pairs':prows,'pair_differences':pairdiff,'paired_species':speciespaired,'flows':flows,'judge_cross':cross,'source_groups':groups,'source_files':filegroups,'source_dependency':j(W/'source_dependency_summary.json'),'coverage':coverage,'breakdown':breakdown,'p5':{'stats':stat(pv),'species':{s:stat([p['p_at_5'] for p in p5 if p['species']==s]) for s in sorted({p['species'] for p in p5})}},'formulas':formulas,'special_cases':special,'judge_warnings':warning})
 print(json.dumps({'status':'PASS','question_n':180,'canonical_n':720,'paired_logical_n':27,'paired_arithmetic_n':7,'flow':flows,'source_groups':10,'source_files':3,'judge_literal_warnings':len(warning)},ensure_ascii=False),flush=True)
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
