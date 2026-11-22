from __future__ import annotations
import json,re
from pathlib import Path
from collections import defaultdict
import numpy as np
from src.unified_rag_v4.retrieval import UnifiedRetriever as BaseRetriever
from src.unified_rag_v4.common import embed,tokens

class UnifiedRetriever(BaseRetriever):
    def __init__(self,work,reranker_path):
        super().__init__(work,reranker_path)
        self.archive=None
        self.config=json.loads((self.work/'build_config.json').read_text(encoding='utf-8'))
        self.page_visual_assets={}
        with self.connect() as con:
            for row in con.execute("SELECT d.sha256,e.page,e.asset_id,a.path FROM document_elements e JOIN documents d USING(document_id) JOIN media_assets a USING(asset_id) WHERE e.kind='PAGE_RENDER'"):
                self.page_visual_assets.setdefault((row['sha256'],row['page']),[]).append(dict(row))

    def scope_check(self,question,target,chunk):
        law=chunk.get('restrictions_json',{}).get('law_source_status')
        if law:
            historical=any(x in question for x in ('歷史','舊版','修正對照','總說明','逐條說明'))
            accepted=('OFFICIAL_LATEST_AVAILABLE_PAGE_SNAPSHOT','OFFICIAL_ATTACHMENT_BYTES_MATCH','OFFICIAL_DATE_AND_ALL_ARTICLES_MATCH')
            if law['status'] not in accepted and not historical:
                return False,'HISTORICAL_OR_UNVERIFIED_LAW_NOT_DEFAULT_CURRENT_EVIDENCE:'+law['status']
            if law['law_id']=='M0130023' and any(x in question for x in ('劑量','用量','停藥','使用對象')):
                # The attachment is saved and searchable in full, but a PDF
                # layout pass is not independent verification of a dosing row.
                if chunk.get('restrictions_json',{}).get('kind')=='TABLE_ROWS':
                    return False,'DRUG_TABLE_OBJECT_DOSE_AND_WITHDRAWAL_RELATION_REQUIRES_VERIFIED_ROW_PROTOCOL'
                scope=chunk.get('species_scope',[])
                if scope and target not in scope:return False,'DRUG_ATTACHMENT_SCOPE_DOES_NOT_IDENTIFY_TARGET_SPECIES'
        return super().scope_check(question,target,chunk)

    def visual_candidates(self,question,fish):
        if self.clip is None and self.image_rows and any(x in question for x in ['圖片','照片','圖像','顯微','示意圖']):
            from transformers import CLIPModel,CLIPProcessor
            folder=Path(self.config['clip_model_directory'])
            self.clip=(CLIPModel.from_pretrained(folder,local_files_only=True).eval(),CLIPProcessor.from_pretrained(folder,local_files_only=True))
        result=super().visual_candidates(question,fish)
        if self.clip is None or not any(x in question for x in ['圖片','照片','圖像','顯微','示意圖']):return result
        # Page renders give vector-only diagrams a real visual path back to the
        # same document/page. They never become standalone diagnostic claims.
        import torch
        model,processor=self.clip
        names={'鰻魚':'eel','虱目魚':'milkfish','吳郭魚':'tilapia','石斑魚':'grouper','鱸魚':'sea bass','烏魚':'mullet'}
        prompt=names.get(fish,'fish')+' aquaculture '+('microscopy parasites' if any(t in question for t in ('顯微','寄生')) else 'diagram photograph')
        with torch.inference_mode():
            value=model.get_text_features(**processor(text=[prompt],return_tensors='pt',padding=True))
            if hasattr(value,'pooler_output'):value=value.pooler_output
            vec=value[0].float().numpy();vec/=max(float(np.linalg.norm(vec)),1e-12)
        ranked=sorted(((float(np.dot(np.frombuffer(r['embedding'],dtype=np.float32),vec)),r['asset_id']) for r in self.image_rows),reverse=True)[:30]
        ranks={aid:i for i,(_,aid) in enumerate(ranked,1)}
        for row in self.rows:
            for asset in self.page_visual_assets.get((row['source_sha256'],row['source_page']),[]):
                if asset['asset_id'] in ranks:result.append((ranks[asset['asset_id']],row['chunk_id']))
        return sorted(set(result))

    def _load_archive(self):
        if self.archive is not None:return
        rows=[];vectors=[]
        with self.connect() as con:
            for row in con.execute('SELECT u.*,d.title,e.embedding FROM archive_units u JOIN embedding_cache e USING(content_sha256) LEFT JOIN documents d USING(document_id) ORDER BY u.unit_id'):
                obj=dict(row);vectors.append(np.frombuffer(obj.pop('embedding'),dtype=np.float32));rows.append(obj)
        self.archive={'rows':rows,'vectors':np.asarray(vectors,dtype=np.float32),'byid':{r['unit_id']:i for i,r in enumerate(rows)}}

    def search_archive(self,question,limit=8):
        self._load_archive();data=self.archive
        if not data['rows']:return []
        scores=data['vectors']@embed([question])[0]
        dense=[data['rows'][int(i)]['unit_id'] for i in np.argsort(-scores)[:80]]
        terms=list(dict.fromkeys(tokens(question).split()))
        query=' OR '.join('"'+t.replace('"','')+'"' for t in terms[:90] if t)
        with self.connect() as con:
            lexical=[r[0] for r in con.execute('SELECT unit_id FROM semantic_archive_fts WHERE semantic_archive_fts MATCH ? ORDER BY bm25(semantic_archive_fts) LIMIT 80',(query,))] if query else []
        fused=defaultdict(float)
        for branch in (dense,lexical):
            for rank,key in enumerate(branch,1):fused[key]+=1/(60+rank)
        result=[];seen=set()
        for key,score in sorted(fused.items(),key=lambda item:-item[1]):
            row=data['rows'][data['byid'][key]]
            if row['content_sha256'] in seen:continue
            seen.add(row['content_sha256'])
            result.append({**row,'archive_rrf_score':score,'dense_cosine':float(scores[data['byid'][key]]),
                'answer_verified':False,'not_human_gold':True,'scope':'ALL_PROVIDED_DOCUMENT_DISCOVERY; answer validation remains separate'})
            if len(result)>=limit:break
        return result

    def retrieve(self,question,fish,limit=5):
        result=super().retrieve(question,fish,limit)
        return result
