import json,pathlib
repo=pathlib.Path(r'C:\my project\115_marine_project'); b=repo/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2_existing_corpus'
for n in ['high_risk_source_audit.json','calculation_validation.json','evidence_fact_duplicates.json']:
 d=json.loads((b/n).read_text(encoding='utf-8')); print('\n',n,'keys',list(d) if isinstance(d,dict) else type(d)); print(json.dumps(d,ensure_ascii=True)[:4500])
