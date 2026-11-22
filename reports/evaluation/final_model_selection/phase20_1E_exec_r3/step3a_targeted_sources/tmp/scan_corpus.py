import json,re,hashlib
from pathlib import Path
root=Path(r'C:\my project\115_marine_project')
corpus=root/'data/evaluation/corpus_v2.jsonl'
out=Path(r'C:\my project\115_marine_project\reports\evaluation\final_model_selection\phase20_1E_exec_r3\step3a_targeted_sources\existing_corpus_targeted_hits.jsonl')
terms={
'虱目魚|Disease':(['虱目魚','milkfish','chanos chanos'],['疾病','病原','病害','感染','疫病','streptococcus','鏈球菌','弧菌','寄生蟲']),
'虱目魚|Climate / Cold':(['虱目魚','milkfish','chanos chanos'],['低溫','寒流','冷害','越冬','水溫','temperature','cold','winter']),
'吳郭魚|Climate / Cold':(['吳郭魚','吳郭鱼','羅非魚','羅非鱼','tilapia','oreochromis niloticus'],['低溫','寒流','冷害','越冬','水溫','temperature','cold','winter']),
'石斑魚|Disease':(['石斑魚','石斑鱼','grouper','epinephelus'],['疾病','病原','病害','感染','疫病','病毒','弧菌','寄生蟲']),
'石斑魚|Safe Medication / Law':(['石斑魚','石斑鱼','grouper','epinephelus'],['藥','用藥','藥品','核准','水產動物','藥物殘留','法規']),
'鱸魚|Safe Medication / Law':(['鱸魚','鱸鱼','金目鱸','金目鲈','亞洲海鱸','sea bass','seabass','lates calcarifer'],['藥','用藥','藥品','核准','水產動物','藥物殘留','法規']),
'烏魚|Disease':(['烏魚','乌鱼','烏仔魚','mullet','mugil cephalus'],['疾病','病原','病害','感染','疫病','病毒','弧菌','寄生蟲']),
'鰻魚|Climate / Cold':(['鰻魚','鳗鱼','日本鰻','日本鳗','eel','anguilla japonica'],['低溫','寒流','冷害','越冬','水溫','temperature','cold','winter'])}
rows=[]
for line in corpus.open(encoding='utf-8'):
    try: r=json.loads(line)
    except Exception: continue
    text=' '.join(str(r.get(k) or '') for k in ['text','source_title','topic','species','disease','section','article'])
    lo=text.casefold()
    for cell,(species,topics) in terms.items():
        sm=[x for x in species if x.casefold() in lo]
        tm=[x for x in topics if x.casefold() in lo]
        # Only emit records whose text/source metadata itself mentions a target species alias and at least a topic term.
        if sm and tm:
            score=len(sm)*3+len(tm)
            ss=r.get('source_spans') or []
            first=ss[0] if ss else {}
            rows.append({'cell':cell,'score':score,'species_matches':sm,'topic_matches':tm,'chunk_id':r.get('chunk_id'),'document_id':r.get('document_id'),'page_start':r.get('page_start') or r.get('page'),'page_end':r.get('page_end'),'source_title':r.get('source_title'),'source_id':r.get('source_id'),'source_url':r.get('source_url'),'source_verification_status':r.get('source_verification_status'),'source_verified':r.get('source_verified'),'retrieval_role':r.get('retrieval_role'),'benchmark_eligible':r.get('benchmark_eligible'),'parser_name':r.get('parser_name'),'extraction_method':r.get('extraction_method'),'warnings':r.get('warnings'),'source_checksum':r.get('source_checksum'),'content_checksum':r.get('content_checksum'),'source_span_ids':r.get('source_span_ids'),'support_excerpt':str(r.get('text') or '')[:750],'source_span':first})
rows.sort(key=lambda x:(x['cell'],-x['score'],x['source_title'] or '',x['chunk_id'] or ''))
with out.open('w',encoding='utf-8',newline='\n') as f:
    for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
from collections import Counter
print(json.dumps({'corpus_rows':sum(1 for _ in corpus.open(encoding='utf-8')),'targeted_hit_rows':len(rows),'by_cell':dict(Counter(r['cell'] for r in rows)),'output':str(out)},ensure_ascii=False,indent=2))
for cell in terms:
    print('\n###',cell)
    seen=set(); n=0
    for r in rows:
        if r['cell']!=cell: continue
        key=(r['document_id'],r['page_start'],r['support_excerpt'][:100])
        if key in seen: continue
        seen.add(key); n+=1
        print(json.dumps({k:r.get(k) for k in ['score','species_matches','topic_matches','chunk_id','document_id','page_start','source_title','source_id','source_verification_status','retrieval_role','benchmark_eligible','source_url','source_checksum','support_excerpt']},ensure_ascii=False))
        if n>=5:break
