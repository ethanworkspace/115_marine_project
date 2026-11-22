from pathlib import Path
import json,sqlite3,hashlib,time,sys
W=Path(__file__).resolve().parent
sys.path.insert(0,str(W))
import retrieve_and_verify_180 as p

def main():
 qs=p.read_jsonl(W/'questions_original_180.jsonl')
 target=W/'retrieval_results_alignment_final_180.jsonl'
 prior=p.read_jsonl(target) if target.exists() else []
 done={x['question_id'] for x in prior}
 vectors_path=W/'query_vectors_180.json'
 if vectors_path.exists():
  import numpy as np
  vecs=[np.asarray(v,dtype=np.float32) for v in json.loads(vectors_path.read_text())]
 else:
  vecs=p._embed([q['question_text'] for q in qs]);p.write_json(vectors_path,[v.tolist() for v in vecs])
 rows,recs,sources=p.load_chunks();rr=p.load_reranker();con=sqlite3.connect(p.DB);con.row_factory=sqlite3.Row
 digest=hashlib.sha256(p.DB.read_bytes()).hexdigest()
 with target.open('a',encoding='utf-8') as f:
  for q,v in zip(qs,vecs):
   if q['question_id'] in done:continue
   st=time.time();r=p.collect_retrieval(q,p.make_requirement_profile(q),v,rows,recs,con,rr)
   r.update(corpus_sha256=digest,corpus_version='3.0.1-evidence-alignment',elapsed_seconds=time.time()-st)
   f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()
   print(q['question_id'],len(r['top5']),round(r['elapsed_seconds'],2),flush=True)
 con.close()
if __name__=='__main__':main()
