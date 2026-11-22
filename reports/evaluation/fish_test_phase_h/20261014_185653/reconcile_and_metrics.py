from __future__ import annotations
import collections, datetime as dt, hashlib, json, pathlib

ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'; PG=ROOT/'reports/evaluation/fish_test_auto_annotation_phase_g_20261014_174009'
CORP=ROOT/'data/evaluation/corpus_v2.jsonl'; DOCS=ROOT/'reports/recovery/document_manifest_v3.jsonl'; PHASE_A=ROOT/'reports/evaluation/fish_test_phase_a_20261012'
MODELS=['M1','M2','M3','M4']
def rj(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def rl(p):return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def wj(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def wl(p,rows):
 t=p.with_suffix(p.suffix+'.tmp')
 with t.open('w',encoding='utf-8',newline='\n') as f:
  for x in rows:f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
 t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def completed(cp,qid):
 p=OUT/cp
 if not p.exists():return None
 return next((x for x in rl(p) if x.get('question_id')==qid and x.get('completed') is True),None)
def legacy(cp,qid):
 p=PG/cp
 if not p.exists():return None
 for x in rl(p):
  if x.get('question_id')==qid:
   a=x.get('annotations') or {}
   if set(a)=={'1','2','3','4','5'} and not x.get('error'):
    passages=[]
    for rank in range(1,6):
     a1=a[str(rank)]; lab=a1.get('label')
     lab={'1':'RELEVANT','0':'IRRELEVANT','U':'UNCERTAIN'}.get(str(lab),None)
     if not lab:return None
     passages.append({'rank':rank,'label':lab,'reason_code':a1.get('reason_code'),'reason':a1.get('reason'),'support_type':a1.get('support_type'),'species_applicability':a1.get('species_applicability'),'confidence':a1.get('confidence'),'exact_evidence_text':None,'quote_alignment_status':'not_captured_in_legacy','needs_review':lab=='RELEVANT'})
    return {'question_id':qid,'round':x.get('round'),'completed':True,'passages':passages,'annotator_model':x.get('annotator_model'),'annotator_model_digest':x.get('annotator_digest'),'prompt_version':x.get('prompt_version'),'provenance':'reused_valid_phase_g_checkpoint','exact_quote_available':False}
 return None

questions=rl(RUN/'fish_test_questions_normalized.jsonl'); traces=rl(RUN/'retrieval_trace.jsonl'); corpus=rl(CORP); docs=rl(DOCS)
qmap={q['question_id']:q for q in questions}; tmap={x['question_id']:x for x in traces}; cmap={x['chunk_id']:x for x in corpus}; dmap={x['document_id']:x for x in docs}
doc_urls=collections.defaultdict(list); corpus_urls=collections.defaultdict(list)
for d in docs:
 if d.get('source_url'):doc_urls[d['source_url']].append(d)
for c in corpus:
 if c.get('source_url'):corpus_urls[c['source_url']].append(c)

# One record per question, with citation locator resolution kept separate from entailment.
source_rows=[]; reference_rows=[]; corpus_url_question_count=0; file_verified_question_count=0
phaseg_ref={x['question_id']:x for x in rl(PG/'reference_answer_verification_180.jsonl')}
for q in questions:
 qid=q['question_id']; urls=list(dict.fromkeys((q.get('candidate_source_urls') or [])))
 for rec in q.get('source_records') or []:
  if isinstance(rec,dict):
   u=rec.get('URL') or rec.get('url') or rec.get('source_url')
   if u and u not in urls:urls.append(u)
 refs=[]; has_corpus=False; files=[]
 for u in urls:
  dd=doc_urls.get(u,[]); cc=corpus_urls.get(u,[]); has_corpus=has_corpus or bool(cc)
  for d in dd:
   fp=ROOT/str(d.get('file_path') or '')
   actual=sha(fp) if fp.is_file() else None
   files.append({'document_id':d.get('document_id'),'path':d.get('file_path'),'exists':fp.is_file(),'manifest_sha256':d.get('checksum'),'actual_sha256':actual,'checksum_match':bool(actual and d.get('checksum')==actual),'version':d.get('version'),'publisher':d.get('organization'),'source_url':u})
  refs.append({'source_url':u,'exact_document_manifest_matches':len(dd),'exact_corpus_chunk_matches':len(cc),'source_ids':q.get('source_ids') or []})
 context_rows=[]
 for c in sorted(tmap[qid].get('contexts',[]),key=lambda x:x.get('top5_rank',999)):
  meta=cmap.get(c.get('chunk_id'),{}); doc=dmap.get(c.get('document_id'),{})
  context_rows.append({'chunk_id':c.get('chunk_id'),'document_id':c.get('document_id'),'rank':c.get('top5_rank'),'page':c.get('page'),'context_sha256':c.get('text_sha256'),'corpus_source_id':meta.get('source_id'),'source_url':meta.get('source_url') or doc.get('source_url'),'source_version':meta.get('source_version') or doc.get('version'),'retrieval_role':meta.get('retrieval_role'),'source_verified':meta.get('source_verified'),'exact_context_text_available':bool(c.get('text')) and hashlib.sha256(c['text'].encode()).hexdigest()==c.get('text_sha256')})
 exact_files=[f for f in files if f['exists'] and f['checksum_match']]
 if has_corpus:corpus_url_question_count+=1
 if exact_files:file_verified_question_count+=1
 status='SOURCE_LOCATOR_ONLY'
 blocker='The workbook has a source URL, but this audit did not verify an exact answer-supporting span.'
 if exact_files:
  status='SOURCE_FILE_AND_CHECKSUM_RESOLVED_SUPPORT_UNVERIFIED'
  blocker='An exact cited source file is locally present with a matching manifest checksum; semantic answer support, source version applicability and exact evidence span remain unverified.'
 elif has_corpus:
  status='CORPUS_DOCUMENT_URL_RESOLVED_SUPPORT_UNVERIFIED'
  blocker='Exact source URL maps to Corpus v2 chunks; answer support, page span and applicability remain unverified.'
 elif not urls:
  status='SOURCE_MISSING'
  blocker='No source URL or source record could be resolved from the normalized test data.'
 row={'question_id':qid,'original_question_id':q.get('original_question_id'),'source_workbook':q.get('source_workbook'),'source_workbook_sha256':q.get('source_workbook_sha256'),'question_bank_excel_row':q.get('question_bank_excel_row'),'species':q.get('species_chinese'),'species_label':q.get('species_label_in_test_data'),'category':q.get('inferred_category'),'question_text':q.get('question_text'),'candidate_reference_answer':q.get('candidate_reference_answer'),'source_ids':q.get('source_ids') or [],'source_records':q.get('source_records') or [],'source_urls':urls,'candidate_source_urls':q.get('candidate_source_urls') or [],'source_location':q.get('source_page_or_exact_span'),'source_url_resolution':refs,'local_originals':files,'retrieved_context_sources':context_rows,'answer_supported':None,'exact_support_span':None,'species_applicability':'not_independently_verified','verification_status':status,'blocker_reason':blocker,'answer_source_status_phase_g':phaseg_ref.get(qid,{}).get('automated_verification_status'),'human_gold_reviewed':False}
 source_rows.append(row)
 refstatus='SOURCE_UNAVAILABLE' if not urls else ('INSUFFICIENT_EVIDENCE' if status!='SOURCE_FILE_AND_CHECKSUM_RESOLVED_SUPPORT_UNVERIFIED' else 'PARTIALLY_SUPPORTED')
 reference_rows.append({'question_id':qid,'verification_status':refstatus,'candidate_reference_answer':q.get('candidate_reference_answer'),'source_ids':q.get('source_ids') or [],'source_urls':urls,'resolved_corpus_source':has_corpus,'verified_local_source_files':exact_files,'exact_support_span':None,'answer_supported':None,'species_applicability':None,'blocker_reason':blocker,'verification_method':'metadata/URL/checksum reconciliation only; no semantic entailment claimed','human_gold_reviewed':False,'status_label':'AI-assisted provenance triage; NOT_HUMAN_GOLD'})
wl(OUT/'source_mapping_recovery_180.jsonl',source_rows)
wl(OUT/'reference_verification_v2.jsonl',reference_rows)
url_refs=[u for r in source_rows for u in r['source_urls']]
resolved_questions=[r for r in source_rows if r['verification_status']=='SOURCE_FILE_AND_CHECKSUM_RESOLVED_SUPPORT_UNVERIFIED']
resolved_files={f['path']:f for r in source_rows for f in r['local_originals'] if f['exists'] and f['checksum_match']}
mapping_summary={'question_count':len(source_rows),'questions_with_source_url':sum(bool(r['source_urls']) for r in source_rows),'unique_source_urls':len(set(url_refs)),'questions_with_exact_corpus_document_url_match':sum(bool(r['source_url_resolution'] and any(x['exact_corpus_chunk_matches'] for x in r['source_url_resolution'])) for r in source_rows),'questions_with_at_least_one_local_original_checksum_match':len(resolved_questions),'unique_local_original_files_checksum_verified':len(resolved_files),'checksum_verified_files':[{'path':p,'sha256':v['actual_sha256'],'source_url':v['source_url'],'version':v['version']} for p,v in resolved_files.items()],'resolved_questions_by_category':dict(collections.Counter(r['category'] for r in resolved_questions)),'questions_with_exact_support_span_verified':0,'questions_with_answer_support_verified':0,'remaining_answers_not_verified':len(source_rows),'status_counts':dict(collections.Counter(r['verification_status'] for r in source_rows)),'human_gold_count':0}
wj(OUT/'source_mapping_recovery_summary.json',mapping_summary)

# Use valid legacy two-pass checkpoints plus any newly completed pilot passes. Never convert missing work to UNCERTAIN.
rounds={1:{},2:{},3:{}}
for rn in (1,2,3):
 p=OUT/f'pilot_round{rn}_v2_5.jsonl'
 if p.exists():
  for x in rl(p):
   if x.get('completed'):rounds[rn][x['question_id']]=x
legacy_map={1:{},2:{}}
for rn,cp in [(1,'annotation_round1_v2_checkpoint.jsonl'),(2,'annotation_round2_v2_checkpoint.jsonl')]:
 for qid in qmap:
  x=legacy(cp,qid)
  if x:legacy_map[rn][qid]=x
all_context=[]; qprec=[]
pilot_ids=set((rj(OUT/'pilot_question_selection.json').get('question_ids') if (OUT/'pilot_question_selection.json').exists() else []))
def getpass(qid,rn):
 if qid in pilot_ids:
  return rounds[rn].get(qid) or legacy_map.get(rn,{}).get(qid)
 return rounds[rn].get(qid) or legacy_map.get(rn,{}).get(qid)
def label_reason_consistent(p):
 if not p:return None
 label=p.get('label'); code=p.get('reason_code')
 allowed={'RELEVANT':{'direct_support','partial_support'},'IRRELEVANT':{'keyword_only','unrelated','species_mismatch'},'UNCERTAIN':{'applicability_uncertain','source_content_uncertain'}}
 return code in allowed.get(label,set()) and not (p.get('species_applicability')=='mismatch' and label=='RELEVANT')
for qid in sorted(qmap):
 q=qmap[qid]; tr=tmap[qid]; rowlabels=[]
 a=getpass(qid,1); b=getpass(qid,2); c=rounds[3].get(qid)
 amap={x['rank']:x for x in a.get('passages',[])} if a else {}; bmap={x['rank']:x for x in b.get('passages',[])} if b else {}; c_map={x['rank']:x for x in c.get('passages',[])} if c else {}
 context_list=sorted(tr.get('contexts',[]),key=lambda x:x.get('top5_rank',999))
 for ctx in context_list:
  rank=ctx.get('top5_rank'); cm=cmap.get(ctx.get('chunk_id'),{}); dm=dmap.get(ctx.get('document_id'),{})
  p1=amap.get(rank); p2=bmap.get(rank); p3=c_map.get(rank)
  completed1=bool(p1); completed2=bool(p2)
  disagreement=bool(p1 and p2 and p1.get('label')!=p2.get('label'))
  final=None; state='INCOMPLETE'; reason='One or more independent annotation passes have not completed.'; selected=None
  if not ctx.get('text') or ctx.get('chunk_id') not in cmap:
   state='SOURCE_MISSING'; reason='Context text or exact Corpus chunk ID is missing from the frozen retrieval trace/Corpus mapping.'
  elif (p1 and not label_reason_consistent(p1)) or (p2 and not label_reason_consistent(p2)):
   state='ANNOTATION_ERROR'; reason='Completed pass has a label/reason-code contradiction; result is excluded from P@5 pending valid reassessment.'
  elif p1 and p2:
   if disagreement:
    if p3:
     final=p3.get('label'); selected=p3; state='UNCERTAIN' if final=='UNCERTAIN' else final; reason='Third AI adjudication completed after independent-pass disagreement.'
    else:
     state='INCOMPLETE'; reason='Two completed passes disagree; third-pass adjudication has not completed.'
   elif p1.get('label')=='UNCERTAIN':
    final='UNCERTAIN'; selected=p1; state='UNCERTAIN'; reason='Both complete independent passes found irreducible content/applicability ambiguity.'
   else:
    final=p1.get('label'); selected=p1; state=final; reason='Both independent passes agree.'
  text=ctx.get('text',''); text_valid=bool(text) and hashlib.sha256(text.encode()).hexdigest()==ctx.get('text_sha256')
  source_meta_status='complete' if all([cm.get('source_id'),ctx.get('chunk_id'),ctx.get('document_id'),ctx.get('page') is not None,ctx.get('text_sha256'),cm.get('source_url') or dm.get('source_url'),cm.get('source_checksum') or dm.get('checksum')]) else 'SOURCE_MISSING_OR_PARTIAL'
  base=selected or p1 or p2 or {}
  source_row={'question_id':qid,'species':q.get('species_chinese'),'category':q.get('inferred_category'),'chunk_id':ctx.get('chunk_id'),'rank':rank,'source_id':cm.get('source_id'),'source_title':cm.get('source_title') or dm.get('title'),'source_url':cm.get('source_url') or dm.get('source_url'),'source_version':cm.get('source_version') or dm.get('version'),'document_id':ctx.get('document_id'),'page':ctx.get('page'),'context_text':text,'context_text_sha256':ctx.get('text_sha256'),'context_sha256':tr.get('context_sha256'),'corpus_version':tr.get('corpus_version'),'retrieval_eligibility':cm.get('retrieval_role'),'source_metadata_status':source_meta_status,'source_verification_status':cm.get('source_verification_status'),'first_pass_completed':completed1,'first_pass_label':p1.get('label') if p1 else None,'first_pass_reason_code':p1.get('reason_code') if p1 else None,'first_pass_consistency_valid':label_reason_consistent(p1),'second_pass_completed':completed2,'second_pass_label':p2.get('label') if p2 else None,'second_pass_reason_code':p2.get('reason_code') if p2 else None,'second_pass_consistency_valid':label_reason_consistent(p2),'third_pass_completed':bool(p3),'adjudication_label':p3.get('label') if p3 else None,'disagreement':disagreement,'final_label':final,'annotation_status':state,'reason':(base.get('reason') or base.get('reason_code') or reason),'reason_code':base.get('reason_code'),'support_type':base.get('support_type'),'species_applicability':base.get('species_applicability'),'exact_evidence_text':base.get('exact_evidence_text'),'model_evidence_quote':base.get('model_evidence_quote'),'quote_alignment_status':base.get('quote_alignment_status','not_captured_in_legacy' if base else None),'needs_review':bool(base.get('needs_review')) or state in {'UNCERTAIN','INCOMPLETE','SOURCE_MISSING','ANNOTATION_ERROR'},'prompt_version':base.get('prompt_version') or (p1 or {}).get('prompt_version') or (p2 or {}).get('prompt_version'),'annotator_model':base.get('annotator_model') or (p1 or {}).get('annotator_model') or (p2 or {}).get('annotator_model'),'annotator_model_digest':base.get('annotator_model_digest') or (p1 or {}).get('annotator_model_digest') or (p2 or {}).get('annotator_model_digest'),'annotation_method':'AI_AUTO_ANNOTATED','human_reviewed':False,'text_integrity_status':'verified' if text_valid else 'failed'}
  all_context.append(source_row); rowlabels.append(source_row)
 labels=[x['final_label'] for x in rowlabels]
 relevant=sum(x=='RELEVANT' for x in labels); irrelev=sum(x=='IRRELEVANT' for x in labels); uncertain=sum(x=='UNCERTAIN' for x in labels); incomplete=sum(x in (None,'INCOMPLETE','SOURCE_MISSING','ANNOTATION_ERROR') for x in labels)
 if len(labels)!=5 or incomplete or any(x['annotation_status']=='ANNOTATION_ERROR' for x in rowlabels): pval=None; status='INCOMPLETE'; lower=upper=None
 elif uncertain: pval=None; status='UNCERTAIN'; lower=relevant/5; upper=(relevant+uncertain)/5
 else: pval=relevant/5; status='COMPUTABLE_AI_AUTO_ANNOTATED'; lower=upper=pval
 qprec.append({'question_id':qid,'species':q.get('species_chinese'),'category':q.get('inferred_category'),'final_labels_rank1_to_5':labels,'relevant_count':relevant,'irrelevant_count':irrelev,'uncertain_count':uncertain,'incomplete_count':incomplete,'p_at_5':pval,'p_at_5_lower_bound':lower,'p_at_5_upper_bound':upper,'status':status,'annotation_method':'AI_AUTO_ANNOTATED','human_gold_reviewed':False,'context_sha256':tr.get('context_sha256'),'corpus_version':tr.get('corpus_version')})
wl(OUT/'context_annotations_recovered_900.jsonl',all_context)
wl(OUT/'context_precision_by_question.jsonl',qprec)
labels_count=collections.Counter(str(x['annotation_status']) for x in all_context)
final_count=collections.Counter(str(x['final_label']) for x in all_context)
validp=[x['p_at_5'] for x in qprec if x['p_at_5'] is not None]
summary={'annotation_method':'AI_AUTO_ANNOTATED','human_gold_count':0,'question_count':len(qprec),'context_count':len(all_context),'full_context_text_checksum_valid_count':sum(x['text_integrity_status']=='verified' for x in all_context),'round1_completed_contexts':sum(x['first_pass_completed'] for x in all_context),'round2_completed_contexts':sum(x['second_pass_completed'] for x in all_context),'both_passes_completed_contexts':sum(x['first_pass_completed'] and x['second_pass_completed'] for x in all_context),'third_pass_completed_contexts':sum(x['third_pass_completed'] for x in all_context),'status_counts':dict(labels_count),'final_label_counts':dict(final_count),'computable_p_at_5_questions':len(validp),'mean_p_at_5':sum(validp)/len(validp) if validp else None,'complete_questions':sum(x['status']=='COMPUTABLE_AI_AUTO_ANNOTATED' for x in qprec),'uncertain_questions':sum(x['status']=='UNCERTAIN' for x in qprec),'incomplete_questions':sum(x['status']=='INCOMPLETE' for x in qprec),'source_missing_contexts':sum(x['annotation_status']=='SOURCE_MISSING' for x in all_context),'all_180_p_at_5_complete':len(validp)==180,'by_species':{},'by_category':{},'not_human_gold':True}
for field,key in [('species','species'),('category','category')]:
 groups=collections.defaultdict(list)
 for r in qprec:groups[r.get(key)].append(r)
 dest=summary['by_species' if field=='species' else 'by_category']
 for g,rr in groups.items():
  vals=[x['p_at_5'] for x in rr if x['p_at_5'] is not None]
  dest[g]={'questions':len(rr),'computable_n':len(vals),'mean_p_at_5':sum(vals)/len(vals) if vals else None}
wj(OUT/'context_precision_summary_v2.json',summary)

# Calculation protocol and model metrics: separate source-verified arithmetic from statement-only diagnostics.
arith=rl(PG/'arithmetic_reference_verification.jsonl'); per=rl(PG/'arithmetic_accuracy_by_model_rows.jsonl'); gs=rj(PG/'arithmetic_accuracy_by_model.json')
calcq=rl(RUN/'fish_test_questions_normalized.jsonl'); calc_ids={q['question_id'] for q in calcq if q.get('calculation_record')}; phase_ids={r['question_id'] for r in arith if r.get('phase_e_candidate')}; union=calc_ids|phase_ids
arith_rows=[]
ar_by={r['question_id']:r for r in arith}
for qid in sorted(union):
 x=ar_by.get(qid,{})
 arith_rows.append({'question_id':qid,'phase_e_candidate':qid in phase_ids,'original_question_structured_calculation':qid in calc_ids,'phase_g_verification':x.get('status'),'formula_source_verified':bool(x.get('formula_source_verified')),'deterministic_recalculation':x.get('deterministic_recalculation'),'candidate_reference_answer':x.get('manual_or_formula_answer'),'candidate_matches_decimal':x.get('candidate_matches_decimal'),'self_contained_operands_in_question':x.get('self_contained_operands_in_question'),'source_verified_arithmetic_status':'NOT_EVALUABLE','source_verified_blocker':'No candidate has a verified authoritative formula/protocol+conditions/source span in Phase G; do not promote arithmetic-only checks.','human_gold_reviewed':False})
wl(OUT/'arithmetic_reference_verification.jsonl',arith_rows)
per_by_q=collections.defaultdict(dict)
for r in per:per_by_q[r['question_id']][r['model_id']]=r
paired_ids=[qid for qid,models in per_by_q.items() if all(m in models and models[m].get('arithmetic_status') in {'correct','incorrect'} for m in MODELS)]
diagnostic={'status':'ARITHMETIC_DIAGNOSTIC; not source-verified domain accuracy; NOT_HUMAN_GOLD','formula_source_verified_candidate_count':sum(bool(x.get('formula_source_verified')) for x in arith),'source_verified_arithmetic':{m:{'required':len(union),'evaluable_n':0,'correct_n':0,'incorrect_n':0,'not_evaluable_n':len(union),'accuracy':None} for m in MODELS},'arithmetic_diagnostic_all_available':gs.get('by_model'),'arithmetic_diagnostic_four_model_paired_question_count':len(paired_ids),'paired_question_ids':paired_ids,'candidate_registry_counts':{'phase_e_62_rows':gs.get('phase_e_candidate_rows'),'normalized_structured_calculation_questions':gs.get('normalized_structured_calculation_questions'),'original_question_record_ids':len(calc_ids),'phase_e_question_ids':len(phase_ids),'union_unique_question_ids':len(union),'self_contained_arithmetic_tasks':gs.get('self_contained_arithmetic_questions')},'limitations':gs.get('notes')}
wj(OUT/'arithmetic_accuracy_verified.json',diagnostic['source_verified_arithmetic'])
wj(OUT/'arithmetic_diagnostic_accuracy.json',diagnostic)

# No rubric can be frozen without verified sources and objective criteria.
logical=rl(PG/'logical_accuracy_by_model.jsonl')
logical_out={'rubric_count':0,'evaluable_question_count':0,'by_model':{m:{'required':180,'evaluable_n':0,'correct_n':0,'incorrect_n':0,'not_evaluable_n':180,'accuracy':None} for m in MODELS},'source_basis':'Phase G reference verification had 0 SOURCE_VERIFIED_AUTOMATED; no independently source-supported objective rubric is available.','human_gold_reviewed':0,'status':'NOT_EVALUABLE; no reliable source-supported Logical Accuracy rubric.','existing_rows_all_not_evaluable':all(r.get('status')=='not_evaluable' for r in logical)}
wj(OUT/'logical_accuracy_verified.json',logical_out)
wl(OUT/'logical_rubric_registry.jsonl',[])

# Protected 636 manifest spot/full recheck and non-destructive compatibility record.
manifest=rj(PHASE_A/'protected_files_manifest.json'); entries=manifest.get('historical_636_recheck',{}).get('entries',[])
checked=0; mismatches=[]
for e in entries:
 rel=str(e.get('path') or ''); p=ROOT/rel
 if not p.is_file():mismatches.append({'path':rel,'status':'missing'});continue
 actual=sha(p); checked+=1
 if actual!=e.get('expected_sha256') or p.stat().st_size!=e.get('current_size_bytes'):mismatches.append({'path':rel,'status':'changed','expected_sha256':e.get('expected_sha256'),'actual_sha256':actual})
sqlite=ROOT/'rag_store.sqlite3'; sqlite_hash=sha(sqlite) if sqlite.is_file() else None
compat={'phase':'H','checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'historical_636_expected':636,'historical_636_manifest_rows':len(entries),'historical_636_rechecked':checked,'historical_636_mismatches':mismatches,'historical_636_unchanged':len(entries)==checked==636 and not mismatches,'sqlite_sha256':sqlite_hash,'sqlite_matches_expected':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'==sqlite_hash,'original_720_generation_outputs_modified':False,'source_workbooks_modified':False,'phase_e_results_modified':False,'phase_g_results_modified':False,'corpus_v2_or_e4_modified':False,'models_or_judge_modified':False,'cleanup_or_deletion_performed':False,'full_repository_pytest_claimed':False}
wj(OUT/'compatibility.json',compat)

print(json.dumps({'questions_with_url':sum(bool(r['source_urls']) for r in source_rows),'questions_with_exact_corpus_url':corpus_url_question_count,'questions_with_local_file_checksum_verified':file_verified_question_count,'context_status_counts':dict(labels_count),'context_final_labels':dict(final_count),'computable_p_at_5':len(validp),'arithmetic_union':len(union),'paired_arithmetic_n':len(paired_ids),'protected_636':compat['historical_636_unchanged']},ensure_ascii=False))
