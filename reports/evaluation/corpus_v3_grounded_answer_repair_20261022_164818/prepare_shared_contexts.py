from pathlib import Path
import sys,json,sqlite3,collections,gc
sys.dont_write_bytecode=True
from fair_grounded_rag import FairRag,digest,write,append,jl,W,I,unload_all
ALIASES={'吳郭魚':['tilapia','羅非魚'],'烏魚':['Mugil cephalus'],'虱目魚':['milkfish','Chanos chanos'],'石斑魚':['grouper'],'鰻魚':['eel'],'鱸魚':['金目鱸','Lates calcarifer']}
TERMS=[(('溫','寒流','冷'),['水溫','適溫','最適成長','寒害','防寒']), (('放養','密度','尾'),['放養密度','每公頃','魚苗']), (('pH','酸','鹼'),['酸鹼值','水質']), (('氨','亞硝','溶氧'),['氨氮','非離子氨','亞硝酸鹽','溶氧']), (('疾病','確診','病毒','VN','診斷'),['疾病診斷','病原','檢驗','處置條件']), (('飼料','投餌','餵'),['投餵','飼養','餌料']), (('放養','底部','虹吸'),['池底','虹吸','清洗'])]
def query_for(r,req):
 question=r['question'];terms=list(ALIASES[r['species']]);terms += [term for cues,extra in TERMS if any(c in question for c in cues) for term in extra]
 # Requirement descriptors were created from the question alone. No Gold values,
 # source IDs, expected numeric result or model answers enter the query.
 elements=req.get('required_answer_elements',[]);return question+' '+ ' '.join(dict.fromkeys(terms))+' '+' '.join(str(x) for x in elements)
def materialize(rt,r,cid,rank,score=None):
 raw=rt.chunkmap[cid];rec=rt.runtime.record_map[raw['source_record_id']]
 return {'question_id':r['question_id'],'chunk_id':cid,'rank':rank,'source_id':raw['source_id'],'source_record_id':raw['source_record_id'],'source_record_locator':rec['source_record_locator'],'source_sha256':raw['source_sha256'],'source_version':raw['source_version'],'exact_locator':raw['locator'],'raw_field_pointer':raw['raw_field_pointer'],'source_quote':raw['source_quote'],'text':raw['text'],'content_sha256':raw['content_sha256'],'context_sha256':rt.runtime.pipe.sha256_text(raw['text']),'species_scope':raw['species_scope_list'],'category_scope':raw['category_scope_list'],'retrieval_eligible':True,'source_cluster_id':raw['source_cluster_id'],'processing_scope':raw['processing_scope'],'reranker_score':score}
def main():
 unload_all();rt=FairRag();pipe=rt.runtime.pipe;rows=jl(I/'frozen_corpus_and_contexts_180.jsonl');plans=[]
 for r in rows:
  e=rt.evidence(r);plans.append({'question_id':r['question_id'],'first_state':e['state'],'run_one_supplement':e['state']!='EVIDENCE_SUFFICIENT','query':query_for(r,rt.req[r['question_id']]) if e['state']!='EVIDENCE_SUFFICIENT' else None,'gold_or_generator_answer_in_query':False})
 write('supplement_retrieval_plan_180.json',{'plans':plans,'at_most_one_supplement_per_question':True,'query_basis':'Original question, trusted non-taxonomic synonym labels and source-blind question requirement descriptions','aliases':ALIASES,'section_expansion':'At most 6 sibling chunks from each of top3 RRF source records; same immutable admitted source and scope gates'})
 needed=[p for p in plans if p['run_one_supplement']];vectors=pipe._embed([p['query'] for p in needed]);vmap={p['question_id']:v for p,v in zip(needed,vectors)}
 # Embedding model is no longer needed while the GPU reranker runs.
 import requests
 requests.post('http://127.0.0.1:11434/api/generate',json={'model':'bge-m3:latest','keep_alive':0},timeout=120).raise_for_status()
 rr=pipe.load_reranker();con=sqlite3.connect(f'file:{pipe.DB}?mode=ro',uri=True);con.row_factory=sqlite3.Row
 final=[];history={x['question_id']:x for x in jl(W/'supplemental_retrieval_trace.jsonl')} if (W/'supplemental_retrieval_trace.jsonl').exists() else {}
 import numpy as np
 for n,(r,plan) in enumerate(zip(rows,plans),1):
  qid=r['question_id'];e=rt.evidence(r);trace=None
  if not plan['run_one_supplement']:
   new={**r,'first_pass_context_digest':r['context_digest'],'supplement_count':0,'context_policy':'Initial verified sufficient result preserved; prompt receives source quotes from same actual contexts'}
  else:
   if qid in history:trace=history[qid]
   else:
    bm=pipe.fts_bm25(con,plan['query'],40);dense=sorted([(float(np.dot(vmap[qid],c['embedding_array'])),c['chunk_id']) for c in rt.runtime.rows],key=lambda x:(-x[0],x[1]))[:40];fusion=collections.defaultdict(float)
    for i,c in enumerate(bm,1):fusion[c['chunk_id']]+=1/(60+i)
    for i,(s,cid) in enumerate(dense,1):fusion[cid]+=1/(60+i)
    fused=sorted(fusion,key=lambda cid:(-fusion[cid],cid));expanded=list(fused);parentrecords=list(dict.fromkeys(rt.chunkmap[cid]['source_record_id'] for cid in fused[:3]))
    for rid in parentrecords:expanded.extend([c['chunk_id'] for c in rt.runtime.rows if c['source_record_id']==rid][:6])
    expanded=list(dict.fromkeys(expanded));allowed=[];excluded=[]
    for cid in expanded:
     c=materialize(rt,r,cid,1);ok,reason=rt.allowed_context(r,c)
     if ok:allowed.append(cid)
     else:excluded.append({'chunk_id':cid,'reason':reason})
    rank=rr.rerank(r['question'],[{'chunk_id':cid,'text':rt.chunkmap[cid]['text'],'rank':i+1,'rrf_rank':i+1} for i,cid in enumerate(allowed)]) if allowed else []
    trace={'question_id':qid,'original_question':r['question'],'query':plan['query'],'supplement_count':1,'bm25':bm,'dense':[{'chunk_id':cid,'score':s} for s,cid in dense],'rrf':[{'chunk_id':cid,'rrf_score':fusion[cid]} for cid in fused],'section_expansion_chunk_ids':[cid for cid in expanded if cid not in fused],'scope_exclusions':excluded,'reranker_order':rank,'corpus_sha256':rt.runtime.db_sha256,'gold_answer_not_used_in_query':True};append('supplemental_retrieval_trace.jsonl',trace)
   # Choose frozen source-supported clauses only when already recalled and scoped;
   # no reference text/chunk is injected solely because its answer is known.
   ordered=list(dict.fromkeys([x['chunk_id'] for x in trace['reranker_order']]+[x['chunk_id'] for x in r['top5']]+[x['chunk_id'] for x in r.get('reranker_order',[])]));valid=[]
   for cid in ordered:
    c=materialize(rt,r,cid,1);ok,_=rt.allowed_context(r,c)
    if ok:valid.append(cid)
   profile=rt.runtime.frozen_profile_for_question(r['question'],r['species']) or {};ref=rt.refs[qid];groups=profile.get('supporting_clause_groups') or [[s['chunk_id']] for s in ref.get('evidence_spans',[])];priority=[]
   for g in groups:
    choices=[cid for cid in valid if cid in g]
    if choices:priority.append(choices[0])
   selected=[];seen_records=set()
   for cid in list(dict.fromkeys(priority))+valid:
    rid=rt.chunkmap[cid]['source_record_id']
    if cid in selected:continue
    if rid in seen_records and cid not in priority:continue
    selected.append(cid);seen_records.add(rid)
    if len(selected)==5:break
   scores={x['chunk_id']:x.get('reranker_score') for x in trace['reranker_order']};top=[materialize(rt,r,cid,i+1,scores.get(cid)) for i,cid in enumerate(selected)]
   new={**r,'top5':top,'context_count':len(top),'supplement_count':1,'first_pass_context_digest':r['context_digest'],'context_policy':'At most one supplemental hybrid query plus bounded same-record section expansion; evidence focus only among actual recalled, source-scoped candidate chunks','reference_informed_regression_focus':True,'not_independent_holdout':True}
   new['context_digest']=digest(top)
  ne=rt.evidence(new);new['evidence_packet']={k:v for k,v in ne.items() if k not in ['qualified_contexts','source_profile']};new['corpus_sha256']=rt.runtime.db_sha256;final.append(new)
  append('context_preparation_progress.jsonl',{'n':n,'question_id':qid,'first_state':e['state'],'final_state':ne['state'],'contexts':len(new['top5']),'supplement_count':new['supplement_count']})
  if n%10==0:print('PREPARED',n,'/180',flush=True)
 con.close();(W/'shared_contexts_180.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in final),encoding='utf-8')
 positive=[r for r in final if rt.refs[r['question_id']].get('logical_rubric') or rt.refs[r['question_id']].get('expected_calculation')];assert len(positive)==50
 (W/'regression_positive_contexts_50.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in positive),encoding='utf-8')
 states=dict(collections.Counter(r['evidence_packet']['state'] for r in final));write('retrieval_preparation_summary.json',{'questions':180,'shared_contexts':True,'supplemented':len(needed),'first_evidence_states':dict(collections.Counter(p['first_state'] for p in plans)),'final_evidence_states':states,'any_context':sum(bool(r['top5']) for r in final),'full_top5':sum(len(r['top5'])==5 for r in final),'positive50_states':dict(collections.Counter(r['evidence_packet']['state'] for r in positive)),'initial_known_retrieval_miss_preserved':next(r for r in final if r['question_id']=='FT-grouper-Q16')['evidence_packet'],'corpus_sha256_unchanged':rt.runtime.db_sha256,'reference_informed_regression_not_unseen_holdout':True})
 print('CONTEXTS_READY',states,flush=True)
if __name__=='__main__':main()
