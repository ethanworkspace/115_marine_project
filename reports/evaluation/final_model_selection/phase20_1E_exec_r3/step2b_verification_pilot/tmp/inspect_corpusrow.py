import json,pathlib
repo=pathlib.Path(r'C:\my project\115_marine_project')
rows=[json.loads(x) for x in (repo/'data/evaluation/corpus_v2.jsonl').read_text(encoding='utf-8').splitlines()]
for id in ['chunk_8aa150216d8651cca9ffbf883102e2ff','chunk_72fbed1cd9645a9bb3b820731edf6c08']:
 r=next(x for x in rows if x.get('chunk_id')==id)
 print(json.dumps({'keys':list(r),'row':{k:r.get(k) for k in ['chunk_id','document_id','page','text','content','content_checksum','checksum','source_checksum','title','document_title'] }},ensure_ascii=True)[:2000])
