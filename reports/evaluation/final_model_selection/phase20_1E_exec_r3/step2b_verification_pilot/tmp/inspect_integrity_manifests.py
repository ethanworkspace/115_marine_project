import json,pathlib
repo=pathlib.Path(r'C:\my project\115_marine_project')
for name in ['reports/evaluation/final_model_selection/phase20_1R/compatibility.json','reports/evaluation/final_model_selection/phase20_1R/readiness.json','reports/evaluation/final_model_selection/phase20_1/phase20_immutable_checksums.json','reports/evaluation/final_model_selection/phase20_1E_exec_r3/baseline_integrity.json']:
 p=repo/name
 print(name,p.exists())
 if p.exists():
  d=json.loads(p.read_text(encoding='utf-8')); print('keys',list(d) if isinstance(d,dict) else type(d));
  if name.endswith('compatibility.json'):
   for k,v in d.items():
    if isinstance(v,list): print(k,len(v),repr(v[:1]))
  elif 'immutable_checksums' in name: print(json.dumps(d,ensure_ascii=True)[:2500])
  elif name.endswith('readiness.json'): print(json.dumps(d,ensure_ascii=True))
