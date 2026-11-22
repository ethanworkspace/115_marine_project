from __future__ import annotations
import json
import re
import sqlite3
import subprocess
import threading
from collections import Counter
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from .common import clean, digest

class WindowsOCR:
    def __init__(self, root, work):
        script=(root/'tools/unified_ocr_worker.ps1').read_text(encoding='utf-8-sig')
        self.process=subprocess.Popen(['powershell.exe','-NoProfile','-Command',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(work/'logs/ocr_stderr.log').open('w',encoding='utf-8'),encoding='utf-8',bufsize=1)
        self.info=json.loads(self.process.stdout.readline());self.lock=threading.Lock();self.work=work
        if not self.info.get('ready'): raise RuntimeError('Traditional Chinese Windows OCR is unavailable')

    def read(self, path):
        key=digest(Path(path).read_bytes());cache=self.work/'ocr_cache';cache.mkdir(exist_ok=True)
        dest=cache/(key+'.json')
        if dest.exists(): return json.loads(dest.read_text(encoding='utf-8'))
        with self.lock:
            self.process.stdin.write(json.dumps({'id':key,'path':str(Path(path).resolve())})+'\n');self.process.stdin.flush()
            row=json.loads(self.process.stdout.readline())
        if row.get('id')!=key: raise ValueError('OCR response identity mismatch')
        dest.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
        return row

    def close(self):
        self.process.stdin.close();self.process.wait(timeout=20)

def create_archive_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,sha256 TEXT UNIQUE NOT NULL,title TEXT NOT NULL,original_format TEXT,publisher TEXT,source_version TEXT,rights_status TEXT NOT NULL,owner_decision TEXT NOT NULL,parse_status TEXT NOT NULL,metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS document_files(path TEXT PRIMARY KEY,document_id TEXT NOT NULL,sha256 TEXT NOT NULL,is_my_data INTEGER NOT NULL,FOREIGN KEY(document_id) REFERENCES documents(document_id));
    CREATE TABLE IF NOT EXISTS raw_documents(document_id TEXT PRIMARY KEY,original_bytes BLOB NOT NULL,FOREIGN KEY(document_id) REFERENCES documents(document_id));
    CREATE TABLE IF NOT EXISTS document_pages(document_id TEXT NOT NULL,page INTEGER NOT NULL,raw_text TEXT NOT NULL,cleaned_text TEXT NOT NULL,width REAL,height REAL,ocr_status TEXT,removed_noise_json TEXT NOT NULL,PRIMARY KEY(document_id,page));
    CREATE TABLE IF NOT EXISTS document_elements(element_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,page INTEGER,kind TEXT NOT NULL,text TEXT NOT NULL,bbox_json TEXT,asset_id TEXT,locator_json TEXT NOT NULL,metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS media_assets(asset_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,media_type TEXT NOT NULL,path TEXT NOT NULL,width INTEGER,height INTEGER,raw_bytes BLOB NOT NULL,ocr_text TEXT,ocr_status TEXT,metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS element_chunks(segment_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,element_ids_json TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,page_start INTEGER,page_end INTEGER,section TEXT,segmentation_method TEXT NOT NULL,quality_status TEXT NOT NULL,chunk_id TEXT);
    CREATE TABLE IF NOT EXISTS semantic_boundaries(document_id TEXT NOT NULL,previous_element_id TEXT,current_element_id TEXT,cosine REAL,break_reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS image_embeddings(asset_id TEXT PRIMARY KEY,embedding BLOB NOT NULL,dimension INTEGER NOT NULL,model TEXT NOT NULL,model_revision TEXT NOT NULL,retrieval_eligible INTEGER NOT NULL);
    ''')

def store_asset(con,work,raw,ext,width,height,ocr=None):
    checksum=digest(raw);aid='ASSET-'+checksum[:24];dest=work/'assets'/(checksum+'.'+ext)
    if not dest.exists(): dest.write_bytes(raw)
    con.execute('INSERT OR IGNORE INTO media_assets VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,checksum,'image/'+ext,str(dest),width,height,raw,'','NOT_RUN',json.dumps({'ocr_is_not_visual_interpretation':True})))
    old=con.execute('SELECT ocr_text,ocr_status FROM media_assets WHERE asset_id=?',(aid,)).fetchone()
    if ocr is not None and old[1]=='NOT_RUN' and width>=70 and height>=35:
        try:
            with Image.open(dest) as im:
                im=im.convert('RGB'); im.thumbnail((2400,2400));ocrpath=work/'assets'/(checksum+'_ocr.png');im.save(ocrpath)
            result=ocr.read(ocrpath)
            con.execute('UPDATE media_assets SET ocr_text=?,ocr_status=?,metadata_json=? WHERE asset_id=?',(clean(result.get('text','')),result['status'],json.dumps(result,ensure_ascii=False),aid))
        except Exception as exc: con.execute('UPDATE media_assets SET ocr_status=?,metadata_json=? WHERE asset_id=?',('OCR_ERROR',json.dumps({'error':repr(exc)}),aid))
    elif width<70 or height<35:
        con.execute("UPDATE media_assets SET ocr_status='TOO_SMALL_FOR_RELIABLE_OCR' WHERE asset_id=? AND ocr_status='NOT_RUN'",(aid,))
    return aid

def add_element(con,doc,page,kind,text,bbox=None,asset=None,metadata=None,ordinal=0):
    eid='EL-'+digest([doc,page,kind,ordinal,bbox,text])[:24]
    locator={'document_id':doc,'physical_page':page,'bbox':bbox,'element_id':eid,'text_offsets':[0,len(text)]}
    con.execute('INSERT OR IGNORE INTO document_elements VALUES(?,?,?,?,?,?,?,?,?)',(eid,doc,page,kind,text,json.dumps(bbox),asset,json.dumps(locator,ensure_ascii=False),json.dumps(metadata or {},ensure_ascii=False)))
    return eid

def local_caption(blocks,bbox):
    candidates=[]
    for _,b,text in blocks:
        overlap=max(0,min(b[2],bbox[2])-max(b[0],bbox[0]))
        if (re.search(r'(?:圖|Fig\.?|Figure)\s*[\d一二三四五六七八九十]',text,re.I)
            and -12<=b[1]-bbox[3]<100 and overlap/max(1,min(b[2]-b[0],bbox[2]-bbox[0]))>=.45
            and b[2]-b[0]<=1.6*(bbox[2]-bbox[0])):
            candidates.append((abs(b[1]-bbox[3]),text))
    return min(candidates,default=(None,''))[1]

def extract_pdf(con,rec,work,ocr):
    docid=rec['document_id'];path=Path(rec['parse_path']);page_n=0;issues=[]
    with fitz.open(path) as doc:
        # Only geometrically marginal repeated text is a removable header/footer.
        margins=Counter()
        for page in doc:
            for b in page.get_text('blocks'):
                if len(b)>6 and b[6]==0 and (b[3]<page.rect.height*.09 or b[1]>page.rect.height*.92):
                    t=clean(b[4])
                    if 1<len(t)<90: margins[t]+=1
        repeats={s for s,n in margins.items() if n>=max(3,len(doc)*.6)}
        for pageno,page in enumerate(doc,1):
            page_n+=1;raw=page.get_text('text',sort=True);removed=[]
            tableboxes=[];tables=[]
            try:
                finder=page.find_tables()
                for t in finder.tables:
                    cells=t.extract()
                    if len(cells)>=2 and max(map(len,cells),default=0)>=2:
                        cells=[[None if x is None else clean(x) for x in row] for row in cells]
                        bbox=list(t.bbox);tableboxes.append(fitz.Rect(bbox)); tables.append((bbox,cells))
            except Exception as exc: issues.append({'page':pageno,'type':'TABLE_EXTRACTION_ERROR','error':repr(exc)})
            blocks=[]
            for idx,b in enumerate(page.get_text('blocks',sort=True)):
                if len(b)>6 and b[6]!=0: continue
                text=clean(b[4]);box=fitz.Rect(b[:4])
                if not text: continue
                if text in repeats and (box.y1<page.rect.height*.09 or box.y0>page.rect.height*.92):
                    removed.append({'text':text,'bbox':list(box),'reason':'REPEATED_MARGIN_ONLY'});continue
                if re.fullmatch(r'\d{1,4}',text) and (box.y0>page.rect.height*.92 or box.y1<page.rect.height*.06):
                    removed.append({'text':text,'bbox':list(box),'reason':'MARGINAL_PAGE_NUMBER'});continue
                if any((box&t).get_area()/max(box.get_area(),1)>.85 for t in tableboxes): continue
                blocks.append((idx,list(box),text))
            ocrstatus='NATIVE_TEXT'
            if len(re.sub(r'\s','',raw))<25 or raw.count('\ufffd')>max(5,len(raw)*.03):
                pagepath=work/'assets'/(docid+'-page-'+str(pageno)+'.png')
                page.get_pixmap(matrix=fitz.Matrix(1.7,1.7)).save(pagepath)
                result=ocr.read(pagepath);ocrstatus=result['status']
                if result.get('text'):
                    # OCR remains explicitly uncertain; no invented table structure.
                    text=clean(result['text']);add_element(con,docid,pageno,'SCAN_OCR',text,list(page.rect),metadata={'ocr':result,'quality':'OCR_REQUIRES_REVIEW'})
                    if not blocks: blocks=[(-1,list(page.rect),text)]
                else: issues.append({'page':pageno,'type':'SCAN_WITHOUT_READABLE_OCR','status':ocrstatus})
            for idx,bbox,text in blocks:
                add_element(con,docid,pageno,'PARAGRAPH',text,bbox,metadata={'reading_order':'PDF_BLOCK_LAYOUT','ocr_page':ocrstatus!='NATIVE_TEXT'},ordinal=idx)
            for idx,(bbox,cells) in enumerate(tables):
                near=[text for _,b,text in blocks if b[3]<=bbox[1] and bbox[1]-b[3]<130]
                after=[text for _,b,text in blocks if b[1]>=bbox[3] and b[1]-bbox[3]<70]
                text='\n'.join(' | '.join('' if x is None else x.replace('\n',' ') for x in row) for row in cells)
                clip=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=fitz.Rect(bbox));aid=store_asset(con,work,clip.tobytes('png'),'png',clip.width,clip.height)
                add_element(con,docid,pageno,'TABLE',text,bbox,aid,{'cells':cells,'caption_context':near[-2:],'footnote_candidates':after[:2],'quality':'STRUCTURE_EXTRACTED_NOT_EXPERT_VERIFIED','missing_cells':sum(x is None for r in cells for x in r)},ordinal=idx)
            for idx,info in enumerate(page.get_image_info(xrefs=True)):
                try:
                    xref=info.get('xref',0);bbox=list(info['bbox'])
                    if xref:
                        image=doc.extract_image(xref);imagebytes=image['image'];ext=image['ext'];width=image['width'];height=image['height']
                    else:
                        pix=page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),clip=fitz.Rect(bbox));imagebytes=pix.tobytes('png');ext='png';width=pix.width;height=pix.height
                    aid=store_asset(con,work,imagebytes,ext,width,height,ocr)
                    ocrtext,ocrstate=con.execute('SELECT ocr_text,ocr_status FROM media_assets WHERE asset_id=?',(aid,)).fetchone()
                    caption=local_caption(blocks,bbox)[:1500]
                    text='\n'.join(t for t in [caption,ocrtext] if t)
                    add_element(con,docid,pageno,'IMAGE',text,bbox,aid,{'caption':caption,'ocr_status':ocrstate,'xref':xref,'image_understanding':'OCR_AND_NEARBY_CAPTION_ONLY_NO_DIAGNOSTIC_VISION','caption_association':'GEOMETRIC_CANDIDATE_NOT_EXPERT_VERIFIED'},ordinal=idx)
                except Exception as exc: issues.append({'page':pageno,'type':'IMAGE_EXTRACTION_ERROR','error':repr(exc)})
            con.execute('INSERT OR REPLACE INTO document_pages VALUES(?,?,?,?,?,?,?,?)',(docid,pageno,raw,'\n\n'.join(b[2] for b in blocks),page.rect.width,page.rect.height,ocrstatus,json.dumps(removed,ensure_ascii=False)))
            if pageno%20==0:
                con.commit();print(json.dumps({'document':docid,'page':pageno,'total':len(doc)},ensure_ascii=False),flush=True)
    return {'pages':page_n,'issues':issues}
