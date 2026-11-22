"""One versioned corpus; FTS/BGE-M3/RRF/BGE reranker plus optional image search."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from collections import defaultdict
import numpy as np
from .common import FISH,NARROW,embed,sha_file,tokens,verify_embedding_model

class UnifiedRetriever:
    def __init__(self, work, reranker_path):
        verify_embedding_model()
        self.work=Path(work)
        self.manifest=json.loads((self.work/'corpus_manifest.json').read_text(encoding='utf-8'))
        self.db=Path(self.manifest['database'])
        self.sha=sha_file(self.db)
        if self.sha!=self.manifest['database_sha256']: raise ValueError('Unified database differs from frozen build manifest')
        self.reranker_path=Path(reranker_path);self.reranker=None;self.clip=None
        con=self.connect()
        self.sources={r['source_id']:dict(r) for r in con.execute('SELECT * FROM sources')}
        self.rows=[];vectors=[]
        for r in con.execute('SELECT * FROM chunks WHERE retrieval_eligible=1 ORDER BY chunk_id'):
            item=dict(r);vectors.append(np.frombuffer(item.pop('embedding'),dtype=np.float32))
            for key in ('species_scope','category_scope','restrictions_json'):
                value=item[key]
                try: parsed=json.loads(value) if isinstance(value,str) else value
                except json.JSONDecodeError: parsed={'source_text':value} if key=='restrictions_json' else [value] if value else []
                if key=='restrictions_json' and not isinstance(parsed,dict): parsed={'limitations':parsed}
                if key!='restrictions_json' and not isinstance(parsed,list): parsed=[str(parsed)] if parsed else []
                item[key]=parsed
            item['exact_locator']=item['locator'];item['source_title']=self.sources[item['source_id']]['title']
            item['media_assets']=[]
            seg=con.execute('SELECT element_ids_json FROM element_chunks WHERE chunk_id=?',(item['chunk_id'],)).fetchone()
            if seg:
                for eid in json.loads(seg[0]):
                    asset=con.execute('SELECT a.asset_id,a.path,e.kind,e.page,e.metadata_json FROM document_elements e JOIN media_assets a ON e.asset_id=a.asset_id WHERE e.element_id=?',(eid,)).fetchone()
                    if asset:
                        a=dict(asset);a['metadata']=json.loads(a.pop('metadata_json'));item['media_assets'].append(a)
            self.rows.append(item)
        self.vectors=np.asarray(vectors,dtype=np.float32)
        if self.vectors.shape!=(len(self.rows),1024): raise ValueError('Vector/chunk mapping invalid')
        self.map={r['chunk_id']:r for r in self.rows};self.ids=[r['chunk_id'] for r in self.rows]
        self.record_map={r['source_record_id']:dict(r) for r in con.execute('SELECT * FROM source_records')}
        self.image_rows=[dict(r) for r in con.execute('SELECT * FROM image_embeddings WHERE retrieval_eligible=1')]
        con.close()

    def connect(self):
        con=sqlite3.connect(self.db.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row;return con

    def scope_check(self, question, target, chunk):
        if chunk['chunk_id'] not in self.map: return False,'NOT_IN_VERSIONED_RETRIEVAL_SET'
        src=chunk['source_id'];scope=chunk.get('species_scope',[]);restr=chunk.get('restrictions_json',{})
        if src.startswith('DGBAS-') and all(y in question for y in ['2015','2020']): return False,'CROSS_YEAR_COMPARISON_NOT_ADMITTED'
        kind=restr.get('scope_kind',chunk.get('taxonomy_level',''))
        technical=('疾病','病害','感染','用藥','停藥','劑量','適溫','水質','溶氧','防寒','fcr','sgr')
        if (src.startswith('DGBAS-') or kind=='STATISTICAL_NATIVE_FIELDS_ONLY') and any(x in question.casefold() for x in technical): return False,'STATISTICS_SCOPE_CANNOT_SUPPORT_TECHNICAL_OR_DISEASE_CLAIMS'
        if kind=='NAME_CODE_LOOKUP_ONLY':
            if any(x in question for x in ['病原','寄生蟲','病毒','細菌','黴菌']): return False,'FISH_NAME_CODE_IS_NOT_A_PATHOGEN_REFERENCE'
            if not any(x in question for x in ['學名','俗名','英文名稱','中文名稱','代碼','代號']):
                return False,'NATIVE_CODE_LABEL_LOOKUP_ONLY_NOT_PROFESSIONAL_BIOLOGY'
            native=restr.get('native_record',{})
            names={name.strip().casefold() for key in ('中文名稱','英文名稱','學名','俗名')
                   for name in re.split(r'[、,，;；/\n]',str(native.get(key,''))) if name.strip()}
            def exact_name(alias):
                alias=alias.casefold()
                # Only original complete names or explicit scientific genus
                # labels qualify. A shared character (烏喉 vs 烏魚) never does.
                return alias in names or alias+'類' in names or (
                    alias.isascii() and ' ' not in alias and any(n.startswith(alias+' ') for n in names))
            if target in FISH and not any(exact_name(a) for a in FISH[target]):
                return False,'NATIVE_NAME_FIELDS_DO_NOT_IDENTIFY_TARGET_SPECIES'
            requested=[n for n in NARROW if n in question]
            if requested and not any(exact_name(n) for n in requested):
                return False,'NATIVE_NAME_FIELDS_DO_NOT_IDENTIFY_REQUESTED_NARROW_TAXON'
            return True,'NATIVE_ORIGINAL_NAME_FIELDS_MATCH_NOT_HUSBANDRY_EVIDENCE'
        if kind=='STATISTICAL_NATIVE_FIELDS_ONLY':
            if not any(x in question for x in ['統計','生產量','漁獲量','公頃','普查']): return False,'NATIVE_STATISTICS_NOT_HUSBANDRY_KNOWLEDGE'
            if src=='DGBAS-79395-2015':
                if not any(x in question for x in ['2015','104年']) or any(x in question for x in ['趨勢','跨年','比較','成長率']): return False,'DGBAS_2015_SINGLE_YEAR_SCOPE_ONLY'
                return True,'EXACT_2015_NATIVE_LABELS_AND_AREAS_ONLY'
            native=restr.get('native_record',{});year=str(native.get('year',''))
            return (bool(year and re.search(r'(?<!\d)'+re.escape(year)+r'(?!\d)',question)), 'STATISTICS_REQUIRE_EXACT_NATIVE_YEAR_CODE_NO_CALENDAR_INFERENCE')
        if src.startswith('DGBAS-'):
            if not ('2020' in question or '109年' in question) or not any(x in question for x in ['統計','面積','公頃','縣市','普查']) or any(x in question for x in ['跨年','趨勢','成長率']): return False,'STATISTICS_SINGLE_YEAR_NATIVE_FIELDS_ONLY'
        if src=='MOA-EEL-STOCKING-OPEN-41845': return False,'UNDATED_STATISTICS_CONTEXT_ONLY'
        if src=='MOA-ANIMAL-DRUG-OPEN-7274' and not any(x in question for x in ['許可證','成分','藥品名稱','藥名','適應症']): return False,'PERMIT_NOT_HUSBANDRY_OR_DOSING_GUIDANCE'
        general=kind in ('GENERAL_REGULATION','GENERAL_AQUACULTURE') or src.startswith('DGBAS-')
        if kind=='GENERAL_FRESHWATER_AQUACULTURE':
            if target not in ('吳郭魚','鰻魚') and '淡水' not in question: return False,'FRESHWATER_SCOPE_REQUIRES_APPLICABLE_ENVIRONMENT'
            general=True
        if not general:
            if target=='通用養殖': return False,'SPECIFIC_SPECIES_NEEDS_QUERY_SCOPE'
            if target not in scope: return False,'EXPLICIT_SPECIES_SCOPE_MISMATCH'
        for narrow in NARROW:
            if narrow in scope and narrow not in question:
                # White eel and Japanese eel are aliases, not eel-family synonyms.
                if narrow in ('白鰻','日本鰻') and any(x in question for x in ['白鰻','日本鰻']): continue
                return False,'NARROW_TAXON_NOT_PROVEN_FOR_BROAD_QUERY:'+narrow
        return True,'SOURCE_USAGE_AND_ORIGINAL_SCOPE_ACCEPTED_NOT_ANSWER_GOLD'

    def rerank(self, query, rows):
        if not rows: return []
        if self.reranker is None:
            from src.evaluation.reranker_runtime import CrossEncoderRuntime
            self.reranker=CrossEncoderRuntime(self.reranker_path,device='cpu',max_length=512,batch_size=4)
        tokenizer=self.reranker.tokenizer
        budget=max(64,self.reranker.max_length-len(tokenizer(query)['input_ids'])-8)
        passages=[];owners=[];locations=[]
        for owner,row in enumerate(rows):
            text=row['text'];encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)
            offsets=encoded['offset_mapping']
            if len(offsets)<=budget:
                passages.append(text);owners.append(owner);locations.append([0,len(text)])
            else:
                for start in range(0,len(offsets),max(1,budget-48)):
                    end=min(start+budget,len(offsets));a=offsets[start][0];b=offsets[end-1][1]
                    passages.append(text[a:b]);owners.append(owner);locations.append([a,b])
                    if end==len(offsets): break
        scored=self.reranker.score_pairs(query,passages);values=[float('-inf')]*len(rows)
        for row in rows: row['reranker_windows']=[]
        for owner,span,score in zip(owners,locations,scored):
            rows[owner]['reranker_windows'].append({'start':span[0],'end':span[1],'score':score})
            values[owner]=max(values[owner],score)
        return values

    def visual_candidates(self, question, fish):
        if not self.image_rows or not any(x in question for x in ['圖片','照片','圖像','顯微','示意圖']): return []
        import torch
        from transformers import CLIPModel,CLIPProcessor
        if self.clip is None:
            folder=self.work/'models/clip-vit-base-patch32';self.clip=(CLIPModel.from_pretrained(folder,local_files_only=True).eval(),CLIPProcessor.from_pretrained(folder,local_files_only=True))
        model,processor=self.clip
        name={'鰻魚':'eel','吳郭魚':'tilapia','石斑魚':'grouper','鱸魚':'sea bass','烏魚':'mullet','虱目魚':'milkfish'}.get(fish,'fish')
        prompt=name+' fish aquaculture '+('microscope gills parasites' if '顯微' in question or '寄生' in question else 'aquaculture photograph')
        with torch.inference_mode():
            output=model.get_text_features(**processor(text=[prompt],return_tensors='pt',padding=True))
            if hasattr(output,'pooler_output'): output=output.pooler_output
            v=output[0].float().detach().numpy();v/=max(np.linalg.norm(v),1e-12)
        scored=sorted([(float(np.dot(np.frombuffer(r['embedding'],dtype=np.float32),v)),r['asset_id']) for r in self.image_rows],reverse=True)[:20]
        assets={aid:i for i,(_,aid) in enumerate(scored,1)}
        return sorted([(assets[a['asset_id']],r['chunk_id']) for r in self.rows for a in r.get('media_assets',[]) if a['asset_id'] in assets])

    def retrieve(self, question, fish, limit=5):
        qvector=embed([question])[0];scores=self.vectors@qvector
        allowed=[];scope_exclusions=[]
        for i,row in enumerate(self.rows):
            ok,reason=self.scope_check(question,fish,row)
            if ok: allowed.append(i)
            else: scope_exclusions.append({'chunk_id':row['chunk_id'],'reason':reason})
        raw_dense=[(self.ids[i],float(scores[i])) for i in np.argsort(-scores)[:80]]
        chosen=sorted(allowed,key=lambda i:-scores[i])[:80]
        dense=[(self.ids[i],float(scores[i])) for i in chosen]
        terms=list(dict.fromkeys(tokens(question).split()))
        query=' OR '.join('"'+t.replace('"','')+'"' for t in terms[:90] if t)
        with self.connect() as con:
            bm_raw=[(r['chunk_id'],float(r['bm'])) for r in con.execute('SELECT chunk_id,bm25(unified_fts) bm FROM unified_fts WHERE unified_fts MATCH ? ORDER BY bm LIMIT 80',(query,))] if query else []
            bm=[(r['chunk_id'],float(r['bm'])) for r in con.execute('SELECT chunk_id,bm25(unified_fts) bm FROM unified_fts WHERE unified_fts MATCH ? AND chunk_id IN ('+','.join('?' for _ in allowed)+') ORDER BY bm LIMIT 80',[query]+[self.ids[i] for i in allowed])] if query and allowed else []
        fused=defaultdict(float)
        for branch in (bm,dense):
            for rank,(cid,_) in enumerate(branch,1): fused[cid]+=1/(60+rank)
        visual=self.visual_candidates(question,fish)
        for rank,cid in visual: fused[cid]+=.5/(60+rank)
        accepted=[];excluded=[]
        for cid,rrf in sorted(fused.items(),key=lambda p:-p[1]):
            ok,reason=self.scope_check(question,fish,self.map[cid])
            if ok: accepted.append({**self.map[cid],'rrf_score':rrf})
            else: excluded.append({'chunk_id':cid,'reason':reason})
        candidates=accepted[:40]
        ranks=self.rerank(question,candidates)
        for item,value in zip(candidates,ranks): item['reranker_score']=value
        ordered=sorted(candidates,key=lambda r:r['reranker_score'],reverse=True)
        result=[];record_hits=defaultdict(int);context_chars=0;budget_exclusions=[]
        for item in ordered:
            if record_hits[item['source_record_id']]>=2: continue
            if context_chars+len(item['source_quote'])>3600:
                budget_exclusions.append(item['chunk_id']);continue
            record_hits[item['source_record_id']]+=1
            context_chars+=len(item['source_quote'])
            result.append({**item,'rank':len(result)+1})
            if len(result)==limit: break
        # Keep adjacent source chunks available as a separate, traceable context
        # expansion; never manufacture five results or bypass scope checks.
        return {'corpus_version':self.manifest['version'],'corpus_sha256':self.sha,'question':question,'species':fish,
                'bm25':[{'chunk_id':c,'score':s} for c,s in bm],'dense':[{'chunk_id':c,'score':s} for c,s in dense],
                'unfiltered_bm25':[{'chunk_id':c,'score':s} for c,s in bm_raw],'unfiltered_dense':[{'chunk_id':c,'score':s} for c,s in raw_dense],
                'corpus_source_scope_eligible_count':len(allowed),'corpus_scope_exclusion_counts':dict(__import__('collections').Counter(x['reason'] for x in scope_exclusions)),
                'rrf':[{'chunk_id':c,'score':s} for c,s in sorted(fused.items(),key=lambda p:-p[1])],
                'source_species_exclusions':excluded,'reranker':[{'chunk_id':r['chunk_id'],'score':r['reranker_score']} for r in ordered],
                'context_budget_characters':3600,'actual_context_characters':context_chars,'context_budget_exclusions':budget_exclusions,
                'visual_branch':visual,'top5':result,'candidate_count_before_scope':len(fused),'candidate_count_after_scope':len(accepted),
                'relevance_truth_claim':False,'empty_result_reason':None if result else 'NO_APPLICABLE_ELIGIBLE_CANDIDATES'}
