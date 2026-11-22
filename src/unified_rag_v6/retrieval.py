from __future__ import annotations
import json
from collections import defaultdict
import numpy as np
from src.unified_rag_v5.retrieval import UnifiedRetriever as ParentRetriever


class UnifiedRetriever(ParentRetriever):
    """Keep answer safeguards; make every recovered image discoverable."""
    def __init__(self,work,reranker_path):
        super().__init__(work,reranker_path)
        self.media_page_links=defaultdict(list)
        self.media_info={}
        with self.connect() as con:
            for row in con.execute('SELECT a.asset_id,a.path,a.ocr_text,a.ocr_status,a.width,a.height FROM media_assets a'):
                self.media_info[row['asset_id']]=dict(row)
            for row in con.execute('SELECT DISTINCT d.sha256,e.document_id,d.title,e.page,e.asset_id,e.kind FROM document_elements e JOIN documents d USING(document_id) WHERE e.asset_id IS NOT NULL'):
                item=dict(row)
                self.media_page_links[(row['sha256'],row['page'])].append(item)
                self.media_info[row['asset_id']].setdefault('source_positions',[]).append(item)

    def _image_ranking(self,question,fish,limit=30):
        # Use the pinned CLIP branch already loaded by the parent; no external
        # vision service, figure diagnosis or invented caption is introduced.
        self.visual_candidates(question if any(w in question for w in ('圖片','照片','圖像','顯微','示意圖')) else question+' 圖片',fish,_internal=True)
        import torch
        model,processor=self.clip
        names={'鰻魚':'eel','虱目魚':'milkfish','吳郭魚':'tilapia','石斑魚':'grouper','鱸魚':'sea bass','烏魚':'mullet'}
        terms=[]
        for zh,en in [('寄生','parasite microscopy'),('鰓','gill'),('池塘','pond'),('水質','water quality diagram'),('表格','table'),('黴菌','fungal disease photograph'),('細菌','bacteria microscopy')]:
            if zh in question:terms.append(en)
        prompt=names.get(fish,'fish')+' aquaculture '+' '.join(terms or ['photograph diagram'])
        with torch.inference_mode():
            v=model.get_text_features(**processor(text=[prompt],return_tensors='pt',padding=True))
            if hasattr(v,'pooler_output'):v=v.pooler_output
            vector=v[0].float().detach().numpy();vector/=max(float(np.linalg.norm(vector)),1e-12)
        ranked=sorted(((float(np.dot(np.frombuffer(row['embedding'],dtype=np.float32),vector)),row['asset_id']) for row in self.image_rows),reverse=True)
        return ranked[:limit]

    def visual_candidates(self,question,fish,_internal=False):
        found=super().visual_candidates(question,fish)
        if _internal or self.clip is None or not any(w in question for w in ('圖片','照片','圖像','顯微','示意圖')):return found
        ranking=self._image_ranking(question,fish,30)
        ranks={aid:rank for rank,(_,aid) in enumerate(ranking,1)}
        for row in self.rows:
            for link in self.media_page_links.get((row['source_sha256'],row['source_page']),[]):
                if link['asset_id'] in ranks:found.append((ranks[link['asset_id']],row['chunk_id']))
        # The main retrieve() still checks source/species eligibility. An image
        # match only finds a page; it cannot confer evidence sufficiency.
        return sorted(set(found))

    def search_images(self,question,fish,limit=8):
        return [{**self.media_info[aid],'clip_cosine':score,'not_expert_visual_interpretation':True,'answer_eligible_by_image_similarity':False} for score,aid in self._image_ranking(question,fish,limit)]
