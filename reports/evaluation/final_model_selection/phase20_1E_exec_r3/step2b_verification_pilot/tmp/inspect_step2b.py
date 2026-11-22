import json, pathlib
repo=pathlib.Path(r'C:\my project\115_marine_project')
base=repo/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2_existing_corpus'
for name in ['screening_processing_report.json','existing_corpus_evidence_matrix.json','targeted_gap_registry.json','readiness_after_step2.json','tests.json','compatibility.json']:
 d=json.loads((base/name).read_text(encoding='utf-8'))
 print('\n###',name, type(d).__name__)
 if isinstance(d,dict): print('keys',list(d)[:30])
 if name=='screening_processing_report.json':
  print(json.dumps(d,ensure_ascii=False)[:5000])
 if name=='existing_corpus_evidence_matrix.json':
  rows=d.get('cells', d.get('matrix',d))
  print('rowtype',type(rows).__name__)
  print(json.dumps(rows[:2] if isinstance(rows,list) else list(rows.items())[:2],ensure_ascii=False)[:2500])
 if name=='targeted_gap_registry.json': print(json.dumps(d,ensure_ascii=False)[:2500])
 if name=='tests.json': print(json.dumps(d,ensure_ascii=False)[:4000])
 if name=='compatibility.json': print(json.dumps(d,ensure_ascii=False)[:1800])
pool=json.loads((repo/'data/evaluation/grounded/evidence_pool_v1.jsonl').read_text(encoding='utf-8').splitlines()[0])
print('\nPOOL SAMPLE KEYS',list(pool), json.dumps(pool,ensure_ascii=False)[:1500])
