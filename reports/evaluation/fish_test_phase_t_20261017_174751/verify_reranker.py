import hashlib, json, sys, time
from pathlib import Path
root=Path.cwd(); out=root/'reports/evaluation/fish_test_phase_t_20261017_174751'
snapshot=root/'.venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
expected={'config.json':'13dcd6c31d9fec9d1d8e158702072f62d7fa7d312a64b9fe057bec9a08cfe41a','model.safetensors':'d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286','sentencepiece.bpe.model':'cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865','special_tokens_map.json':'8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835','tokenizer.json':'69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15','tokenizer_config.json':'7e4c1cc848840aeccdd763458c18dd525eb0f795c992e00ebe9c28554e7db2d4'}
files={};
for name,want in expected.items():
 p=snapshot/name; got=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
 files[name]={'exists':p.is_file(),'sha256':got,'expected_sha256':want,'matches':got==want,'size_bytes':p.stat().st_size if p.is_file() else None}
revision=(snapshot.parent.parent/'refs'/'main')
ref=revision.read_text().strip() if revision.exists() else None
config=json.loads((snapshot/'config.json').read_text()) if (snapshot/'config.json').exists() else {}
report={'model_id':'BAAI/bge-reranker-v2-m3','required_revision':'953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','snapshot_path':str(snapshot),'snapshot_path_revision_matches':snapshot.name=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','hf_main_ref':ref,'hf_main_ref_matches':ref=='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','files':files,'architecture':config.get('model_type'),'architectures':config.get('architectures'),'num_labels':config.get('num_labels'),'local_only':True,'network_download_attempted':False,'status':'hash_checked'}
if not all(x['matches'] for x in files.values()):
 report['runtime_load_status']='blocked_checksum_mismatch'
else:
 sys.path.insert(0,str(root)); from src.evaluation.reranker_runtime import CrossEncoderRuntime
 try:
  model=CrossEncoderRuntime(snapshot,device='cuda',max_length=512,batch_size=4)
  pairs=[('金目鱸適用之養殖管理說明','此段來源說明金目鱸養殖管理與疾病預防作業。'),('金目鱸適用之養殖管理說明','此段描述一般天氣預報資料欄位。')]
  s1=model.score_pairs(pairs[0][0],[pairs[0][1]])
  ss=model.score_pairs(pairs[0][0],[pairs[0][1]])
  ids=[{'chunk_id':'smoke-a','text':pairs[0][1],'rank':2},{'chunk_id':'smoke-b','text':pairs[1][1],'rank':1}]
  ranked=model.rerank(ids,pairs[0][0])
  report.update({'runtime_load_status':'loaded','load_info':model.load_info.__dict__,'smoke_scores':s1,'deterministic_repeat_equal':s1==ss,'identity_preserved':{r['chunk_id'] for r in ranked}=={'smoke-a','smoke-b'},'ranked_ids':[r['chunk_id'] for r in ranked],'status':'pass' if s1==ss and {r['chunk_id'] for r in ranked}=={'smoke-a','smoke-b'} else 'fail'})
 except Exception as e: report.update({'runtime_load_status':'failed','error_type':type(e).__name__,'error':str(e),'status':'fail'})
(out/'reranker_runtime_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'runtime_load_status':report.get('runtime_load_status'),'revision':ref,'architecture':config.get('model_type'),'load_seconds':report.get('load_info',{}).get('model_load_seconds'),'device':report.get('load_info',{}).get('device'),'file_matches':sum(x['matches'] for x in files.values()),'file_count':len(files),'error':report.get('error')},ensure_ascii=True))
