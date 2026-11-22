from pathlib import Path
import json,hashlib,shutil,datetime,sqlite3,collections,requests,subprocess,sys
sys.stdout.reconfigure(encoding='utf-8')
W=Path(__file__).resolve().parent; R=W.parents[2]
I=R/'reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def write(n,x): (W/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jl(p):return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def baseline():
 m=json.loads((R/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json').read_text(encoding='utf-8-sig'))
 rows=[]
 for x in m['files']:
  p=R/x['path'];actual=sha(p) if p.exists() else None
  rows.append({**x,'actual_sha256':actual,'unchanged':actual==x['sha256']})
 return {'files':rows,'total':len(rows),'unchanged':sum(x['unchanged'] for x in rows),'checked_at':datetime.datetime.now().astimezone().isoformat()}
if __name__=='__main__':
 for n in ['corpus','runtime','test_logs','streams','prompts','outputs','previews']: (W/n).mkdir(exist_ok=True)
 b=baseline();write('protected_baseline_before.json',b)
 assert b['total']==b['unchanged']==636,'Protected baseline mismatch; stop'
 names=['rag_v3_runtime.py','retrieve_and_verify_180.py','questions_original_180.jsonl','reference_runtime_profiles.json','runtime_evidence_profiles_frozen.json','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','corpus_evidence_availability_180.jsonl','retrieval_evidence_hits_180.jsonl','context_precision_label_status.json','retrieved_chunk_support_labels.jsonl','corpus_source_registry_alignment.json','corpus_successor_manifest.json','evaluation_configuration_frozen.json','semantic_clause_equivalence_registry.json','question_requirement_profiles_reviewed_180.jsonl','finite_fact_provenance.jsonl','chunk_scope_corrections.jsonl']
 for n in names:shutil.copy2(I/n,W/n)
 shutil.copy2(I/'runtime/grounded_answer_engine_v2.py',W/'runtime/grounded_answer_engine_v2.py')
 shutil.copy2(I/'corpus/marine_hybrid_rag_corpus_v3.sqlite3',W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')
 rs=jl(I/'retrieval_results_alignment_final_180.jsonl');qs=jl(W/'questions_original_180.jsonl');refs=jl(W/'verified_reference_answers_v3.jsonl')
 availability={r['question_id']:r for r in jl(W/'corpus_evidence_availability_180.jsonl')}
 con=sqlite3.connect(f"file:{W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'}?mode=ro",uri=True);con.row_factory=sqlite3.Row
 assert con.execute('pragma integrity_check').fetchone()[0]=='ok'
 rows=[]
 for r in rs:
  contexts=r['top5']
  for c in contexts:
   db=con.execute('select * from chunks where chunk_id=?',(c['chunk_id'],)).fetchone()
   assert db and db['text']==c['text'] and db['source_record_id']==c['source_record_id'] and c['source_quote'] in c['text']
  digest=hashlib.sha256(json.dumps(contexts,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  r.update(run_id=W.name,context_digest=digest,source_group_ids=availability[r['question_id']]['original_record_group_keys'])
  rows.append(r)
 (W/'frozen_corpus_and_contexts_180.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
 full=[r for r in refs if r.get('evidence_verification_level')=='ANSWERABLE_AUTO_SOURCE_CHECKED']
 counts={'questions':len(qs),'full_support':len(full),'logical':sum(bool(r.get('logical_rubric')) for r in refs),'arithmetic':sum(bool(r.get('expected_calculation')) for r in refs),'any_context':sum(bool(r['top5']) for r in rows),'full_top5':sum(len(r['top5'])==5 for r in rows),'total_contexts':sum(len(r['top5']) for r in rows),'source_groups':len({g for r in full for g in availability[r['question_id']]['original_record_group_keys']}),'gaps':dict(collections.Counter(a['gap_classification'] for a in availability.values()))}
 assert len(qs)==len(rows)==len(refs)==len({r['question_id'] for r in rows})==180
 tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=30).json()
 write('ollama_tags_before.json',tags)
 config=json.loads((W/'evaluation_configuration_frozen.json').read_text(encoding='utf-8'))
 for mid,m in config['models'].items():
  actual=next(x for x in tags['models'] if x['name']==m['tag']);assert actual['digest']==m['digest']
  show=requests.post('http://127.0.0.1:11434/api/show',json={'model':m['tag']},timeout=30).json();write(f'test_logs/{mid}_metadata.json',show)
  if mid=='M3': assert show['model_info']['general.architecture']=='llama'
 write('input_reconciliation.json',{'counts':counts,'source':str(I),'sources_admission_reapproval_required':False,'human_gold':0,'expected_production_sqlite_sha256':'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087','snapshot_sha256':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'prior_retrieval_version_difference':{'parent':'3.0.0','parent_any_context':177,'parent_full_top5':133,'current':counts,'interpretation':'Different corpus eligibility, species scope, finite facts and post-rerank record deduplication; no controlled degradation claim'}})
 write('input_snapshot_manifest.json',{'source':str(I),'copied':[{'path':str(p.relative_to(W)),'sha256':sha(p)} for p in W.rglob('*') if p.is_file() and p.suffix in ['.py','.json','.jsonl','.sqlite3']]})
 print(json.dumps(counts,ensure_ascii=False))
