import json
from pathlib import Path
qs=[json.loads(x) for x in Path('reports/evaluation/fish_test_run_20261012_152244/fish_test_questions_normalized.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
q={x['question_id']:x for x in qs}['FT-milkfish-Q09']
r=[json.loads(x) for x in Path('reports/evaluation/fish_test_phase_t_20261017_174751/retrieval_results_v3.jsonl').read_text(encoding='utf-8').splitlines() if x.strip() and json.loads(x)['question_id']=='FT-milkfish-Q09'][0]
print(json.dumps({'question':q,'top5':r['reranked_top5']},ensure_ascii=True,indent=2))

