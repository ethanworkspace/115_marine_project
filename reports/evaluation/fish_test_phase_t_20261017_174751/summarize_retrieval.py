import json,collections
from pathlib import Path
p=Path('reports/evaluation/fish_test_phase_t_20261017_174751/retrieval_results_v3.jsonl')
rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
print('SUMMARY',Path('reports/evaluation/fish_test_phase_t_20261017_174751/retrieval_results_summary.json').read_text(encoding='utf-8'))
print('BY_CATEGORY',json.dumps({k:dict(v) for k,v in collections.defaultdict(collections.Counter).items()},ensure_ascii=True))
by=collections.defaultdict(collections.Counter)
for r in rows: by[(r['category'],r['retrieval_status'])]['n']+=1
print('CATEGORY_STATUS',json.dumps({str(k):dict(v) for k,v in by.items()},ensure_ascii=True))
bysp=collections.defaultdict(collections.Counter)
for r in rows: bysp[(r['species'],r['retrieval_status'])]['n']+=1
print('SPECIES_STATUS',json.dumps({str(k):dict(v) for k,v in bysp.items()},ensure_ascii=True))
print('RETRIEVED_IDS',json.dumps([{'id':r['question_id'],'species':r['species'],'category':r['category'],'n':r['final_top5_count'],'sources':sorted(set(x['source_id'] for x in r['reranked_top5']))} for r in rows if r['final_top5_count']],ensure_ascii=True))
