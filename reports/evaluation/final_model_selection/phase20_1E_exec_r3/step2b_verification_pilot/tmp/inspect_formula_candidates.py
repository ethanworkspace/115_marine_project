import json,pathlib
p=pathlib.Path(r'C:\my project\115_marine_project\reports\evaluation\final_model_selection\phase20_1E_exec_r3\step2_existing_corpus\calculation_formula_registry_v1.jsonl')
for line in p.read_text(encoding='utf-8').splitlines()[:8]:
 d=json.loads(line); print(json.dumps(d,ensure_ascii=True)[:1800])
