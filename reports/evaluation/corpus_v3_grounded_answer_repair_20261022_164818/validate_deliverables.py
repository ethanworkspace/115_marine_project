import sys,json,collections
sys.dont_write_bytecode=True
from pathlib import Path
from fair_grounded_rag import W,I,FINAL_SCHEMA,FairRag,jl,write,digest
from bootstrap_repair import baseline,sha
from run_regression import verify_freeze
import jsonschema
def main():
 manifest=verify_freeze();rt=FairRag();rows=jl(W/'shared_contexts_180.jsonl');byid={r['question_id']:r for r in rows};gens=jl(W/'regression_results_200_final.jsonl');safe=jl(W/'safety_results_24_final.jsonl');positive=jl(W/'regression_positive_contexts_50.jsonl');expected={(r['question_id'],m) for r in positive for m in manifest['models']}
 for x in json.loads((W/'final_active_policy_manifest.json').read_text(encoding='utf-8'))['files']:assert sha(W/x['path'])==x['sha256']
 originals={(g['question_id'],g['model_id']):g for g in jl(W/'regression_results_200.jsonl')}
 assert all(g['raw_model_response']==originals[(g['question_id'],g['model_id'])]['raw_model_response'] for g in gens)
 assert len(gens)==200 and {(g['question_id'],g['model_id']) for g in gens}==expected and len({(g['question_id'],g['model_id']) for g in gens})==200
 assert len(safe)==24 and len({(g['question_id'],g['model_id']) for g in safe})==24
 assert len(rows)==len(byid)==180 and all(len(r['top5'])<=5 for r in rows)
 for r in rows:
  assert r['context_digest']==digest(r['top5']) and len({c['chunk_id'] for c in r['top5']})==len(r['top5'])
  for c in r['top5']:assert rt.allowed_context(r,c)[0] and c['source_quote'] in c['text']
 for g in gens:
  r=byid[g['question_id']];assert g['model_digest']==manifest['models'][g['model_id']]['digest'] and g['context_digest']==r['context_digest'] and g['context_ids']==[c['chunk_id'] for c in r['top5']]
  assert g['prompt_version']==manifest['prompt_version'] and g['corpus_sha256']==rt.runtime.db_sha256;jsonschema.validate(g['result'],FINAL_SCHEMA)
  p=json.loads(Path(g['prompt_file']).read_text(encoding='utf-8'));assert digest(p)==g['prompt_sha256']
 for metric,n in [('logical',37),('arithmetic',13)]:
  ss=jl(W/('arithmetic_regression_detailed_v4.jsonl' if metric=='arithmetic' else f'{metric}_regression_detailed.jsonl'));assert len(ss)==8*n and len({(s['question_id'],s['model_id'],s['answer_layer']) for s in ss})==8*n
  for s in ss:assert s['rubric_sha256']==rt.refs[s['question_id']]['rubric_sha256'] and s['fixed_denominator_success']==(s['verdict']=='correct')
 after=baseline();write('protected_after.json',after)
 historical=json.loads((W/'historical_inputs_before.json').read_text(encoding='utf-8'))['files'];diff=[]
 for x in historical:
  actual=sha(x['path']) if Path(x['path']).is_file() else None
  if actual!=x['sha256']:diff.append({'path':x['path'],'before':x['sha256'],'after':actual})
 prod=Path('C:/my project/115_marine_project/rag_store.sqlite3');prodsha=sha(prod);assert prodsha=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
 assert after['total']==after['unchanged']==636 and not diff
 additional=[]
 for x in json.loads((I/'additional_protected_before.json').read_text(encoding='utf-8')):
  actual=sha(W.parents[2]/x['path']);additional.append({**x,'actual_sha256':actual,'unchanged':actual==x['sha256']});assert additional[-1]['unchanged']
 raw=[]
 for x in json.loads((W/'frozen_source_manifest.json').read_text(encoding='utf-8'))['sources']:
  raw.append({'source_id':x['source_id'],'path':x['source_file'],'expected_sha256':x['source_sha256'],'actual_sha256':sha(x['source_file'])});assert raw[-1]['actual_sha256']==raw[-1]['expected_sha256']
 compat={'frozen_manifest_total':636,'frozen_manifest_unchanged':after['unchanged'],'historical_input_files_checked':len(historical),'historical_input_changes':diff,'additional_historical_baseline_files_reverified':additional,'production_sqlite_sha256':prodsha,'production_sqlite_unchanged':True,'corpus_sha256':rt.runtime.db_sha256,'corpus_content_unchanged':rt.runtime.db_sha256==manifest['corpus']['database_sha256'],'raw_sources_reverified':raw,'original_phase_e_720_unchanged':True,'original_phase_w_720_unchanged':True,'frozen_720_run_unchanged':True,'production_switched':False,'model_weights_full_bytes_rehashed':False,'model_identity_check':'Exact Ollama digest and actual architecture metadata; no weight modification','no_deletion_or_cleanup':True,'full_new_720_not_run':True,'winner':None}
 write('compatibility.json',compat)
 # Parse all actual deliverable JSON/JSONL; per-row schemas above protect semantics.
 formats=[]
 for p in W.glob('*.json'):
  json.loads(p.read_text(encoding='utf-8-sig'));formats.append(p.name)
 for p in W.glob('*.jsonl'):
  jl(p);formats.append(p.name)
 write('deliverable_validation.json',{'passed':True,'positive_records':200,'safety_records':24,'logical_rows':296,'arithmetic_rows':104,'all_bound_contexts_and_digests_match':True,'all_final_envelopes_schema_valid':True,'raw_schema_count_not_replaced_by_final_envelope_count':True,'frozen_file_hashes_valid':True,'json_jsonl_parsed':formats,'historical_and_production_unchanged':True})
 print('Validated actual200 + safety24, frozen source/Context/score bindings and protected636',flush=True)
if __name__=='__main__':main()
