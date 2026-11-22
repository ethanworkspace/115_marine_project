import json, collections
from pathlib import Path
root=Path.cwd()
manifest={}
for line in (root/'reports/recovery/document_manifest_v3.jsonl').read_text(encoding='utf-8-sig').splitlines():
 if line.strip():
  r=json.loads(line); manifest[r.get('document_id')]=r
counts=collections.Counter(); docs=collections.defaultdict(lambda:{'chunks':0,'verified_retrieval':0,'eligible':0,'titles':set(),'source_ids':set()})
for line in (root/'data/evaluation/corpus_v2.jsonl').read_text(encoding='utf-8-sig').splitlines():
 if not line.strip(): continue
 r=json.loads(line); did=r.get('canonical_document_id') or r.get('document_id'); d=docs[did]; d['chunks']+=1; d['titles'].add(r.get('source_title')); d['source_ids'].add(r.get('source_id'))
 if r.get('source_verified') is True and r.get('source_verification_status')=='verified' and r.get('retrieval_role')=='retrieval': d['verified_retrieval']+=1
 if r.get('benchmark_eligible') is True: d['eligible']+=1
for did,d in sorted(docs.items(), key=lambda kv: -kv[1]['verified_retrieval']):
 if d['verified_retrieval'] or d['eligible']:
  m=manifest.get(did,{})
  print(json.dumps({'document_id':did,'title':m.get('title') or next(iter(d['titles'])),'publisher':m.get('organization'),'file_path':m.get('file_path'),'checksum':m.get('checksum'),'version':m.get('version'),'legal_status':m.get('legal_status'),'source_verified':m.get('source_verified'),'species':m.get('species'),'chunk_count':d['chunks'],'verified_retrieval_chunks':d['verified_retrieval'],'benchmark_eligible_chunks':d['eligible'],'source_ids':sorted(d['source_ids'])},ensure_ascii=False))
