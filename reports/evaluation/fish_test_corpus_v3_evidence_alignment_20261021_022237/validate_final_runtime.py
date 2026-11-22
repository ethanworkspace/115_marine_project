from pathlib import Path
import sys,json,hashlib
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from rag_v3_runtime import RagV3Runtime,MODELS
def main():
 rt=RagV3Runtime();q='官方建議越冬溝內虱目魚的最高適宜密度是多少？'
 target=W/'final_runtime_real_calls.jsonl';out=[]
 if target.exists():out=[json.loads(s) for s in target.read_text(encoding='utf-8').splitlines()]
 with target.open('a',encoding='utf-8') as f:
  for m in MODELS:
   if any(r['model']['model_id']==m for r in out):continue
   r=rt.answer(q,'虱目魚',m)
   final=r.get('final_response') or {};r['test_pass']=not final.get('abstained') and '1.3' in str(final.get('answer')) and r.get('citation_validation',{}).get('status')=='PASS' and r.get('raw_model_structure_valid') is True and r.get('ttft_visible_answer_seconds') is not None
   r['test_type']='FINAL_RUNTIME_FROZEN_CLAUSE_PROFILE_REAL_STREAMING_GENERATOR'
   out.append(r);f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush();print(m,r['answer_origin'],r['test_pass'],r.get('error'),flush=True)
 (W/'final_runtime_validation.json').write_text(json.dumps({'status':'PASS' if len(out)==4 and all(r['test_pass'] for r in out) else 'FAIL_OR_PARTIAL','runtime_sha256':hashlib.sha256((W/'rag_v3_runtime.py').read_bytes()).hexdigest(),'corpus':rt.corpus_status(),'frozen_reference_profiles_available':len(json.loads((W/'reference_runtime_profiles.json').read_text(encoding='utf-8'))['profiles']),'real_generator_calls':len(out),'results':out},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
