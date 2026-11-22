import sys,json
sys.dont_write_bytecode=True
from fair_grounded_rag_final import W,I,jl,write
from bootstrap_repair import sha
ctx={r['question_id']:r for r in jl(W/'shared_contexts_180.jsonl')};oldctx={r['question_id']:r for r in jl(I/'frozen_corpus_and_contexts_180.jsonl')};p5={r['question_id']:r for r in jl(I/'context_precision_detailed.jsonl') if r['p_at_5'] is not None}
labelpath=I/'retrieved_chunk_support_labels.jsonl';oldlabels=jl(labelpath);mapping={(r['question_id'],r['chunk_id'],r['rank']):r for r in oldlabels};rows=[]
for qid,p in p5.items():
 assert len(ctx[qid]['top5'])==5
 for rank,(c,old) in enumerate(zip(ctx[qid]['top5'],oldctx[qid]['top5']),1):
  assert all(c.get(k)==old.get(k) for k in ['chunk_id','source_id','source_version','source_sha256','text','source_quote','exact_locator'])
  lab=mapping[qid,c['chunk_id'],rank];assert lab['reliable_binary_label_for_exploratory_p5'] and lab['relevance_label'] in [0,1]
  quote=lab.get('exact_evidence_span');quote_ok=not quote or quote in c['text'] or quote==c['source_quote']
  assert quote_ok,(qid,c['chunk_id'],'historical evidence span does not match actual chunk')
  rows.append({**lab,'run_id':W.name,'context_digest':ctx[qid]['context_digest'],'annotation_newly_created':False,'reuse_original_file':str(labelpath),'reuse_original_file_sha256':sha(labelpath),'exact_current_context_verified':True,'historical_evidence_span_verified':quote_ok,'human_gold':False})
 assert sum(r['relevance_label'] for r in rows if r['question_id']==qid)/5==p['p_at_5']
assert len(rows)==60
(W/'context_precision_reused_labels_60.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
write('p5_full_reuse_validation.json',{'passed':True,'exact_context_question_n':len(p5),'reused_binary_chunk_labels':len(rows),'new_annotation_n':0,'old_unverified_labels_not_upgraded':True,'p_at_5_recomputed_from_all60_labels':True,'source_file':str(labelpath),'source_sha256':sha(labelpath),'mean':sum(p['p_at_5'] for p in p5.values())/len(p5),'not_180_question_truth':True,'human_gold':False})
print('Verified60 actual historical binary labels; P5 recomputed on12 identical contexts')
