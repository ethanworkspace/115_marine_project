import json, pathlib, hashlib
repo=pathlib.Path(r'C:\my project\115_marine_project')
pool=[json.loads(x) for x in (repo/'data/evaluation/grounded/evidence_pool_v1.jsonl').read_text(encoding='utf-8').splitlines()]
ids=['chunk_9ce80c7d6737558c8dfc7b188ac72513','chunk_be88525e65be5ca3b0df97a392ae74f5','chunk_b0a6b969645558b79a3dd0281d99f144','chunk_8aa150216d8651cca9ffbf883102e2ff','chunk_c198c6516b725316b349248ccd7de814','chunk_7dcf98ca3cda581eb1629cc5cc8a1442','chunk_2dae6e21944154a29147711b32516f91','chunk_358b2b00decc5ce68ad10d931fc2c288','chunk_df83bf2bb32f51e48bbf3f67b2f3c9d1','chunk_37506175731a52cfa5e884e29bef8cc3','chunk_22b9e2d6b62b584ba72d5ca49b776c61','chunk_72fbed1cd9645a9bb3b820731edf6c08','chunk_adf0bebfc2c45ef29d6553130ddc1a54','chunk_094d0f7c030350cf9a57f9fa83b68d9b']
for id in ids:
 p=next(x for x in pool if x['chunk_id']==id)
 print(json.dumps({k:p.get(k) for k in ['chunk_id','species','category','risk_level','document_id','page','pages','document_title','source_verified','source_verification_status','source_checksum','content_checksum','evidence_quality_status','warnings','quality_reasons','text']},ensure_ascii=True))
