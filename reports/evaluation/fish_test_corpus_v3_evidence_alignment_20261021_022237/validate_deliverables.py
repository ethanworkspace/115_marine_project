from pathlib import Path
import json,hashlib,sqlite3,collections
import openpyxl
W=Path(__file__).resolve().parent;ROOT=W.parents[2]
required=['corpus_evidence_availability_180.jsonl','retrieval_evidence_hits_180.jsonl','retrieved_chunk_support_labels.jsonl','source_vs_retrieval_failure_report.md','previous_13_answers_revalidation.jsonl','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','context_precision_label_status.json','rag_v3_real_e2e_results.json','repository_pytest_results.json','evaluation_readiness_final.json','evaluation_readiness_final.xlsx','corpus_v3_evidence_alignment_report.md','compatibility.json']
checks=[]
def check(name,condition,detail=None):
 checks.append({'name':name,'passed':bool(condition),'detail':detail})
def jl(n):return [json.loads(s) for s in (W/n).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
for n in required:check('exists:'+n,(W/n).is_file() and (W/n).stat().st_size>0)
format_rows=[]
# Explicit top-level outputs only: no recursive venv/node_modules/temp scanning.
for p in [*W.glob('*.json'),*W.glob('*.jsonl')]:
 try:
  data=jl(p.name) if p.suffix=='.jsonl' else json.loads(p.read_text(encoding='utf-8-sig'))
  format_rows.append({'file':p.name,'valid':True,'records':len(data) if isinstance(data,list) else None})
 except Exception as e:format_rows.append({'file':p.name,'valid':False,'error':repr(e)})
check('all_output_json_jsonl_parse',all(x['valid'] for x in format_rows),format_rows)
availability=jl('corpus_evidence_availability_180.jsonl');hits=jl('retrieval_evidence_hits_180.jsonl');refs=jl('verified_reference_answers_v3.jsonl');labels=jl('retrieved_chunk_support_labels.jsonl');retr=jl('retrieval_results_alignment_final_180.jsonl')
check('question_ids_unique_and_complete',len(availability)==len(refs)==len(hits)==len(retr)==180 and len({r['question_id'] for r in availability})==180)
check('six_species_30_each',set(collections.Counter(r['species'] for r in availability).values())=={30})
check('retrieved_labels_identity_one_to_one',{(r['question_id'],r['chunk_id'],r['rank']) for r in labels}=={(r['question_id'],c['chunk_id'],c['rank']) for r in retr for c in r['top5']})
check('original_792_rows_retained_as_audit',len(jl('original_792_chunk_support_audit.jsonl'))==792)
check('frozen50_reference_answers',sum(r.get('evidence_verification_level')=='ANSWERABLE_AUTO_SOURCE_CHECKED' for r in refs)==50)
frozen=json.loads((W/'evaluation_rubrics_v3_frozen.json').read_text(encoding='utf-8'))
check('source_span_locations_for_all_qualified_references',all(s['original_quote_verified'] for r in frozen['references'] for s in r['evidence_spans']))
check('no_human_gold_promotions',frozen['human_gold']==0 and all(r['human_review_status'].startswith('NOT_HUMAN_GOLD') for r in refs))
wb=openpyxl.load_workbook(W/'evaluation_readiness_final.xlsx',data_only=False)
cached=openpyxl.load_workbook(W/'evaluation_readiness_final.xlsx',data_only=True)
expected=[180,50,49,1,17,17,84,12,174,124,12,.3,37,13,0]
vals=[cached['Overview'].cell(i,2).value for i in range(5,20)]
check('xlsx_reopen_cached_formula_results',all(isinstance(v,(int,float)) and abs(v-e)<1e-9 for v,e in zip(vals,expected)),vals)
check('xlsx_all_9_sheets',len(wb.sheetnames)==9,wb.sheetnames)
check('xlsx_question_ids_match_jsonl',{wb['Questions'].cell(i,1).value for i in range(4,184)}=={r['question_id'] for r in availability})
check('xlsx_context_rows',wb['Context_Labels'].max_row==len(labels)+3,wb['Context_Labels'].max_row-3)
check('xlsx_na_not_zero',sum(isinstance(cached['P5'].cell(i,5).value,(int,float)) for i in range(4,184))==12)
check('xlsx_tables_filters_and_chart',len(wb['Overview']._charts)==1 and all(len(wb[n].tables)==1 for n in wb.sheetnames if n!='Overview'))
errors=[];formulas=[]
for s in wb:
 for row in s:
  for c in row:
   if c.data_type=='e':errors.append((s.title,c.coordinate,c.value))
   if c.data_type=='f':formulas.append((s.title,c.coordinate,c.value))
check('xlsx_no_formula_error_cells',not errors,errors);check('xlsx_summary_formulas_exist',len(formulas)==15,formulas)
cfg=json.loads((W/'evaluation_configuration_frozen.json').read_text(encoding='utf-8'))
check('active_db_and_runtime_match_frozen_configuration',sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')==cfg['active_database_sha256'] and sha(W/'rag_v3_runtime.py')==cfg['runtime_script_sha256'])
check('frozen_636_after_workbook',all(sha(r['path'])==r['expected'] for r in json.loads((W/'frozen_baseline_after_636.json').read_text(encoding='utf-8'))))
compat=json.loads((W/'compatibility.json').read_text(encoding='utf-8'));compat['workbook_reopened_and_validated']=True;compat['workbook_sheet_count']=len(wb.sheetnames);compat['deliverable_validation_pass']=all(c['passed'] for c in checks)
(W/'compatibility.json').write_text(json.dumps(compat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
out={'status':'PASS' if all(c['passed'] for c in checks) else 'FAIL','checks':checks,'required_deliverable_count':len(required),'workbook_sha256':sha(W/'evaluation_readiness_final.xlsx'),'file_validation_scope':'top-level produced JSON/JSONL plus required workbook; no disk inventory/cleanup','new720_generated':False}
(W/'deliverable_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':out['status'],'passed':sum(c['passed'] for c in checks),'total':len(checks),'xlsx_sheets':len(wb.sheetnames),'failed':[c for c in checks if not c['passed']]},ensure_ascii=False))
assert out['status']=='PASS'
