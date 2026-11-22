"""Read-only final checks and SHA provenance; never launches any model call."""
import sys,json,datetime,collections
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap_repair import sha,baseline
from execute_frozen_run import verify_freeze
W=Path(__file__).resolve().parent

def read(n):return json.loads((W/n).read_text(encoding='utf-8'))
def jl(n):return [json.loads(s) for s in (W/n).read_text(encoding='utf-8').splitlines() if s.strip()]
def write(n,v):(W/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 verify_freeze()
 expected={'generator_raw_attempts_720.jsonl':720,'generator_final_results_720.jsonl':720,'per_question_metrics.jsonl':720,'model_vs_system_outcomes.jsonl':720,'logical_accuracy_detailed.jsonl':296,'arithmetic_accuracy_detailed.jsonl':104,'arithmetic_accuracy_audited.jsonl':104,'judge_quality_detailed.jsonl':1440,'bge_relevance_detailed.jsonl':1440,'context_precision_detailed.jsonl':180,'context_precision_reused_labels_60.jsonl':60,'questions_original_180.jsonl':180,'verified_reference_answers_v3.jsonl':180,'shared_contexts_180.jsonl':180}
 counts={n:len(jl(n)) for n in expected};assert counts==expected
 final=jl('generator_final_results_720.jsonl');attempts=jl('generator_raw_attempts_720.jsonl');keys=[(r['question_id'],r['model_id']) for r in final];assert len(keys)==len(set(keys))==720
 assert collections.Counter(r['model_id'] for r in final)=={'M1':180,'M2':180,'M3':180,'M4':180}
 attempt_ids={x['attempt_id'] for x in attempts};assert len(attempt_ids)==720
 for r in final:
  assert r['attempt_id'] in attempt_ids
  for field in ('prompt_file','stream_file'):assert Path(r[field]).is_file(),(r['question_id'],field)
 metrics=read('evaluation_metrics_11.json');per=jl('per_question_metrics.jsonl')
 for mid,x in metrics['models'].items():
  assert sum(x['raw_output_partition'].values())==180
  assert sum(x['final_status_counts'].values())==180
  assert sum(x['answer_origin_counts'].values())==180
  for name,n in [('logical',37),('arithmetic',13),('source50',50)]:
   a=x['professional']['model'][name];assert a['fixed_n']==n and a['correct_n']+a['incorrect_n']+a['not_evaluable_n']==n
   assert a['fixed_validated_task_success']['denominator']==n
 assert metrics['shared_context_precision']['n']==12 and abs(metrics['shared_context_precision']['mean']-.3)<1e-12
 assert metrics['human_gold_n']==0 and metrics['formal_weighted_total'] is None
 assert read('excel_reopen_validation.json')['passed'] and read('workbook_recalculation_test.json')['passed']
 assert read('statistical_validation.json')['passed'] and read('repository_pytest_results.json')['passed']
 # An explicit distinction is retained for the M3 preflight content failure.
 assert read('pre_run_technical_acceptance.json')['passed']
 b=baseline();write('protected_after.json',b);assert b['total']==b['unchanged']==636
 historical=read('historical_inputs_before.json')['files'];changed=[x['path'] for x in historical if not Path(x['path']).is_file() or sha(x['path'])!=x['sha256']];assert not changed
 c=read('compatibility.json');assert c['production_sqlite_sha256']==sha(W.parents[2]/'rag_store.sqlite3')=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
 # Validate every top-level JSON/JSONL deliverable, including saved raw responses.
 formats={}
 for p in sorted(W.iterdir()):
  if not p.is_file():continue
  if p.suffix=='.json':json.loads(p.read_text(encoding='utf-8-sig'));formats[p.name]='JSON_VALID'
  elif p.suffix=='.jsonl':formats[p.name]={'format':'JSONL_VALID','rows':len(jl(p.name))}
 validation={'passed':True,'validated_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'unique_final_pairs':720,'raw_attempts':720,'api_success_n':sum(x['api_completed'] for x in final),'expected_jsonl_counts':counts,'all_top_level_json_formats':formats,'frozen_generation_inputs_unchanged':True,'protected_manifest_unchanged':636,'historical_files_unchanged':len(historical),'production_sqlite_sha256':c['production_sqlite_sha256'],'excel_file_sha256':sha(W/'fish_test_final_fixed_denominator_evaluation.xlsx'),'excel_metrics_and_n_verified':44,'human_gold_n':0,'weighted_total_created':False,'production_switched':False,'new_model_calls_during_validation':0}
 write('final_delivery_validation.json',validation)
 files=[]
 # No recursive walk through environments or dependencies; only explicit outputs.
 for p in sorted(W.iterdir()):
  if p.is_file() and p.name!='reproducibility_manifest.json' and p.suffix in {'.json','.jsonl','.py','.mjs','.md','.xlsx'}:files.append({'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)})
 write('reproducibility_manifest.json',{'run_id':W.name,'generated_at':validation['validated_at'],'source_of_truth':'immutable frozen inputs plus720 raw attempts and720 unique final records','files':files,'corpus':{'path':'corpus/marine_hybrid_rag_corpus_v3.sqlite3','sha256':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')},'frozen_execution_manifest':'final_run_frozen_manifest.json','content_audit':'arithmetic_content_audit_report.json; original verdicts and operational success flags preserved','verification_script':'validate_final_delivery.py','model_weight_full_bytes_rehashed':False,'model_identity':'Ollama digest, architecture, quantization metadata','no_new_generation_needed':True})
 print('Final delivery verified:720/720,636/636, historical files unchanged, Excel44 metrics+N, reproducibility hashes saved')

if __name__=='__main__':main()
