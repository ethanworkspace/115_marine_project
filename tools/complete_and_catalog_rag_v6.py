"""Resumable all-source/media completion and non-destructive my_data catalog."""
from __future__ import annotations
import argparse, collections, csv, hashlib, html, io, json, re, shutil, sqlite3, sys, time, zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
POINTER=ROOT/'research_staging/unified_rag_v6_build_pointer.json'

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def emit(obj):print(json.dumps(obj,ensure_ascii=False),flush=True)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def lines(p,rows):
    with Path(p).open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
def paths():
    p=read(POINTER);w=Path(p['workspace']);r=Path(p['report_directory']);cfg=read(w/'build_config.json');return w,r,cfg
def connect():
    w,r,cfg=paths()
    if (w/'release_frozen.json').exists():raise RuntimeError('Released snapshot is immutable; create a successor.')
    c=sqlite3.connect(w/cfg['database_filename']);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def hook():
    import expand_unified_all_documents_v5 as x
    w,r,cfg=paths();x.W=w;x.R=r;x.CFG=cfg;x.DB=w/cfg['database_filename'];x.CACHE=None
    x.b.WORK=w;x.b.REPORT=r;x.b.CFG=cfg;x.b.DB=x.DB
    return x
def copy_checked(src,dst,expected=None):
    dst.parent.mkdir(parents=True,exist_ok=True)
    expected=expected or sha(src)
    if not dst.exists():shutil.copyfile(src,dst)
    if sha(dst)!=expected:raise ValueError('Copy checksum differs: '+str(dst))
    return expected

def init():
    active=read(ROOT/'research_staging/unified_rag_active.json');parent=Path(active['workspace'])
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    w=ROOT/'research_staging'/('unified_rag_v6_'+stamp);r=ROOT/'reports/evaluation'/w.name
    w.mkdir();r.mkdir()
    for n in ('logs','assets','ocr_cache','live_smoke','app_backup','checkpoints'):(w/n).mkdir()
    cfg=read(parent/'build_config.json')
    cfg.update(version='marine-unified-v6-'+stamp,workspace=str(w),report_directory=str(r),database_filename='marine_unified_v6.sqlite3',parent_database=active['database'],parent_database_sha256=active['database_sha256'],source_frozen_database=active['database'],source_asset_workspace=str(parent),source_catalog_directory=str(ROOT/'my_data'/'RAG來源資料總庫'),current_user_request='所有資料清洗、精準語義切分、圖片表格入庫；所有RAG來源集中複製並分類到my_data；保留歷史資料',current_user_request_at=now())
    dump(w/'build_config.json',cfg);dump(w/'parent_active_snapshot.json',active)
    source=sqlite3.connect(Path(active['database']).as_uri()+'?mode=ro',uri=True);target=sqlite3.connect(w/cfg['database_filename']);source.backup(target);source.close();target.close()
    parent_report=Path(read(parent/'build_config.json')['report_directory'])
    for n in ('official_laws_parsed.json','local_law_version_comparison.json','law_review_by_document.jsonl','official_law_download_manifest.json'):
        if (parent_report/n).exists():shutil.copyfile(parent_report/n,r/n)
    for n in ('professional_platform.py','unified_question_engine.py','launch_info.json'):
        shutil.copyfile(ROOT/'research_staging/app_sessions/launch_20261118_154253'/n,w/'app_backup'/n)
    dump(POINTER,{'workspace':str(w),'report_directory':str(r)})
    x=hook();x.b.baseline('before')
    emit({'workspace':str(w),'report_directory':str(r),'parent_sha256_verified':sha(Path(active['database']))==active['database_sha256']})

def normal_name(s):
    while Path(s).suffix.lower() in ('.pdf','.doc','.docx','.odt','.html','.csv','.json','.xml'):s=Path(s).stem
    return s.casefold().strip()

def inventory():
    from PIL import Image
    w,r,cfg=paths();c=connect();c.executescript('''
    CREATE TABLE IF NOT EXISTS media_files(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,asset_id TEXT NOT NULL,document_id TEXT,page INTEGER,mapping_status TEXT NOT NULL,locator_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS catalog_documents(document_id TEXT PRIMARY KEY,category TEXT,species_json TEXT,title TEXT,original_path TEXT,catalog_path TEXT,sha256 TEXT,classification_basis_json TEXT);
    CREATE TABLE IF NOT EXISTS catalog_assets(asset_id TEXT PRIMARY KEY,catalog_path TEXT,sha256 TEXT);
    CREATE TABLE IF NOT EXISTS processing_checkpoints(stage TEXT,item_id TEXT,status TEXT,detail_json TEXT,PRIMARY KEY(stage,item_id));
    CREATE TABLE IF NOT EXISTS image_pixel_groups(asset_id TEXT PRIMARY KEY,pixel_sha256 TEXT,width INTEGER,height INTEGER);
    ''')
    name_map=collections.defaultdict(set);filename_map=collections.defaultdict(set)
    for row in c.execute('SELECT d.document_id,d.title,f.path FROM documents d JOIN document_files f USING(document_id)'):
        filename_map[normal_name(Path(row['path']).name)].add(row['document_id'])
        name_map[normal_name(Path(row['path']).name)].add(row['document_id']);name_map[normal_name(row['title'])].add(row['document_id'])
    parent=sqlite3.connect(Path(cfg['parent_database']).as_uri()+'?mode=ro',uri=True)
    parent_media={row[0] for row in parent.execute('SELECT sha256 FROM media_assets')};parent.close()
    page_map={}
    for row in c.execute('SELECT document_id,max(page) n FROM document_pages GROUP BY document_id'):page_map[row['document_id']]=row['n']
    assets={row['sha256']:row['asset_id'] for row in c.execute('SELECT asset_id,sha256 FROM media_assets')}
    records=[];new=0;errors=[]
    originals=[p for p in (ROOT/'rag_assets').rglob('*') if p.is_file() and p.suffix.lower() in ('.png','.jpeg','.jpg','.webp','.tif','.tiff','.bmp')]
    for idx,p in enumerate(sorted(originals),1):
        raw=p.read_bytes();checksum=digest(raw);aid=assets.get(checksum);is_new=aid is None
        folder=p.relative_to(ROOT/'rag_assets').parts[0];matches=filename_map.get(normal_name(folder)) or name_map[normal_name(folder)]
        did=next(iter(matches)) if len(matches)==1 else None
        m=re.match(r'p(\d+)(?:_|\.)',p.name,re.I);page=int(m[1]) if m else None
        if did and (page is None or page<1 or page>page_map.get(did,0)):page=None
        mapping='ORIGINAL_FILENAME_IDENTITY_AND_PAGE_RANGE' if did and page else 'SOURCE_ASSOCIATION_REQUIRES_REVIEW'
        try:
            with Image.open(io.BytesIO(raw)) as im:im.verify()
            with Image.open(io.BytesIO(raw)) as im:width,height=im.size;rgb=im.convert('RGB');pixel=digest(str(rgb.size).encode()+rgb.tobytes())
            if is_new:
                aid='ASSET-'+checksum[:24];dest=w/'assets'/(checksum+p.suffix.lower());dest.write_bytes(raw)
                c.execute('INSERT INTO media_assets VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,checksum,'image/'+p.suffix.lower().lstrip('.'),str(dest),width,height,raw,'','NOT_RUN',json.dumps({'recovered_from':str(p),'not_expert_interpretation':True},ensure_ascii=False)))
                assets[checksum]=aid;new+=1
            c.execute('INSERT OR IGNORE INTO image_pixel_groups VALUES(?,?,?,?)',(aid,pixel,width,height))
            loc={'original_path':str(p),'document_id':did,'physical_page':page,'exact_bbox':None,'mapping_status':mapping,'not_an_independently_verified_figure_position':True}
            c.execute('INSERT OR REPLACE INTO media_files VALUES(?,?,?,?,?,?,?)',(str(p),checksum,aid,did,page,mapping,json.dumps(loc,ensure_ascii=False)))
            if did:
                eid='LEGACY-IMAGE-'+digest((did+'|'+str(page)+'|'+str(p)).encode())[:24]
                # Source/page linkage is precise; a bounding box is never guessed.
                c.execute('INSERT OR IGNORE INTO document_elements VALUES(?,?,?,?,?,?,?,?,?)',(eid,did,page,'LEGACY_IMAGE','',json.dumps(None),aid,json.dumps(loc,ensure_ascii=False),json.dumps({'legacy_original_path':str(p),'quality':'IMAGE_NOT_EXPERT_INTERPRETED','bbox_unverified':True},ensure_ascii=False)))
            records.append({'path':str(p),'sha256':checksum,'asset_id':aid,'document_id':did,'page':page,'mapping_status':mapping,'new_asset':checksum not in parent_media,'pixel_sha256':pixel})
        except Exception as exc:errors.append({'path':str(p),'error':repr(exc),'status':'UNREADABLE_IMAGE_NOT_INVENTED'})
        if idx%250==0:c.commit();emit({'stage':'legacy_media_inventory','completed':idx,'total':len(originals),'new_unique_assets':new})
    # Record invalid downloads separately; they are files, not valid legal text.
    failures=[]
    for p in (ROOT/'research_staging/official_downloads/phase_ab_recovery_20261020_172529').glob('*.zip'):
        item={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,'is_valid_zip':False}
        try:
            with zipfile.ZipFile(p) as z:
                bad=z.testzip();item.update(is_valid_zip=bad is None,member_count=len(z.infolist()),bad_member=bad)
        except Exception as exc:item.update(status='INVALID_OR_TRUNCATED_DOWNLOAD',error=repr(exc),not_ingested_as_legal_content=True)
        failures.append(item)
    c.commit();c.close();lines(r/'legacy_media_inventory.jsonl',records);dump(r/'legacy_media_errors.json',errors);dump(r/'incomplete_downloads.json',failures)
    emit({'stage':'inventory_complete','legacy_files':len(records),'new_unique_assets':new,'unmapped':sum(x['document_id'] is None for x in records),'errors':len(errors)})

def media_ocr():
    from PIL import Image
    from src.unified_rag_v4.extraction import WindowsOCR
    from src.unified_rag_v4.common import clean,tokens
    w,r,cfg=paths();c=connect();ocr=WindowsOCR(ROOT,w)
    todo=list(c.execute("SELECT * FROM media_assets WHERE asset_id IN(SELECT asset_id FROM media_files) AND ocr_status='NOT_RUN'"))
    try:
        for n,row in enumerate(todo,1):
            aid=row['asset_id']
            if row['width']<70 or row['height']<35:
                c.execute("UPDATE media_assets SET ocr_status='TOO_SMALL_FOR_RELIABLE_OCR' WHERE asset_id=?",(aid,));continue
            try:
                with Image.open(io.BytesIO(row['raw_bytes'])) as im:
                    im=im.convert('RGB');im.thumbnail((2400,2400));dest=w/'assets'/(aid+'_ocr.png');im.save(dest)
                got=ocr.read(dest);text=clean(got.get('text',''))
                c.execute('UPDATE media_assets SET ocr_text=?,ocr_status=?,metadata_json=? WHERE asset_id=?',(text,got['status'],json.dumps({'ocr_result':got,'not_expert_interpretation':True},ensure_ascii=False),aid))
            except Exception as exc:c.execute('UPDATE media_assets SET ocr_status=?,metadata_json=? WHERE asset_id=?',('OCR_ERROR',json.dumps({'error':repr(exc)}),aid))
            if n%50==0:c.commit();emit({'stage':'recovered_image_ocr','completed':n,'total':len(todo)})
        c.commit()
    finally:ocr.close()
    # Individual OCR regions stay with the same image/page, never merge species
    # across files. Long text breaks at punctuation; native numeric units remain.
    from src.unified_rag_v4.segmentation import split_long
    added=0
    for el in c.execute("SELECT e.*,a.ocr_text,a.ocr_status FROM document_elements e JOIN media_assets a USING(asset_id) WHERE e.kind='LEGACY_IMAGE'").fetchall():
        text=clean(el['ocr_text'])
        c.execute('UPDATE document_elements SET text=? WHERE element_id=?',(text,el['element_id']))
        if not text:continue
        for k,part in enumerate(split_long(text,950)):
            uid='IMG-OCR-'+digest((el['element_id']+'|'+str(k)+'|'+part).encode())[:24]
            loc=json.loads(el['locator_json']);loc.update(element_id=el['element_id'],asset_id=el['asset_id'],ocr_status=el['ocr_status'],ocr_part=k,raw_ocr_retained=True)
            c.execute('INSERT OR IGNORE INTO archive_units VALUES(?,?,?,?,?,?,?,?)',(uid,el['document_id'],None,'LEGACY_IMAGE_OCR_REQUIRES_REVIEW',json.dumps(loc,ensure_ascii=False),part,digest(part.encode()),None));added+=1
    c.commit();c.close();emit({'stage':'media_ocr_complete','images_processed':len(todo),'ocr_archive_units_processed':added})

def vectors():
    x=hook();x.archive_vectors();x.images()

def safe_name(text,limit=90):
    text=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(text)).strip(' .')
    return text[:limit] or '未命名資料'

def category_for(doc,front,sources,law_sources):
    from src.unified_rag_v4.common import species
    text=front[:5000];title=doc['title'];scope=species(text[:1800]);main=[s for s in scope if s in ('虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚')]
    label=main[0] if len(main)==1 else '跨魚種' if main else '適用範圍待核'
    is_official=doc['rights_status']=='OFFICIAL_STATUTORY_SNAPSHOT_ART9'
    law=law_sources.get(doc['sha256'])
    if law or is_official:category='01_官方法規與附件'
    elif 'STATUTORY' in doc['rights_status'] or re.search(r'法規名稱|修正條文對照表|總說明|行政院公報',text[:1500]):category='02_歷史法規與修正說明'
    elif doc['original_format'] in ('.json','.csv','.xml'):
        ids={s['dataset_id'] for s in sources}
        category='06_用藥許可與殘留資料' if '7274' in ids else '03_養殖技術與問答' if '114846' in ids else '07_統計與名稱代碼'
    elif re.search(r'寄生蟲|黴菌性|鰓部疾病|病毒性|細菌性|疾病防治|疾病診斷|疾病介紹',text[:1800]+title):category='04_疾病與生物安全'
    elif re.search(r'防寒|寒害|氣候|水質|溶氧|氨氮|環境監測',text[:600]+title):category='05_水質環境與氣候'
    elif re.search(r'用藥|藥品|殘留|停藥|使用規範',text[:500]+title):category='06_用藥許可與殘留資料'
    else:category='03_養殖技術與問答'
    if category.startswith(('01_','02_','06_','07_')):label='通用或依原文對象'
    return category,label,scope,{'basis':'Original printed front matter plus preserved source roles/dataset identity; organizational tags are not species applicability approval','front_excerpt':text[:700],'source_ids':[s['source_id'] for s in sources],'not_filename_only':True}

def catalog():
    w,r,cfg=paths();c=connect();lib=Path(cfg['source_catalog_directory']);lib.mkdir(parents=True,exist_ok=True)
    overview=lib/'00_資料總覽';overview.mkdir(exist_ok=True)
    laws=read(r/'official_laws_parsed.json');law_sources={law['source']['sha256']:law for law in laws.values()}
    source_rows=[dict(x) for x in c.execute('SELECT * FROM sources')];sources_by_sha=collections.defaultdict(list)
    for s in source_rows:sources_by_sha[s['source_sha256']].append(s)
    docs=[];canonical={};classification={};pathmap=[]
    for d in [dict(x) for x in c.execute('SELECT * FROM documents ORDER BY document_id')]:
        meta=json.loads(d['metadata_json']);old=Path(meta['primary_path']);front='\n'.join(x[0] for x in c.execute('SELECT cleaned_text FROM document_pages WHERE document_id=? AND page<=6 ORDER BY page',(d['document_id'],)))
        cat,fish,tags,basis=category_for(d,front,sources_by_sha[d['sha256']],law_sources)
        law=law_sources.get(d['sha256']);display=law['title'] if law else d['title']
        ext=d['original_format'];name=safe_name(normal_name(display),100)+'__'+d['sha256'][:12]+ext
        dest=lib/cat/fish/name;copy_checked(old,dest,d['sha256']);canonical[d['sha256']]=dest;classification[d['document_id']]=(cat,fish,display)
        original_paths=[dict(x) for x in c.execute('SELECT path,is_my_data FROM document_files WHERE document_id=?',(d['document_id'],))]
        for p in original_paths:pathmap.append({'document_id':d['document_id'],'original_path':p['path'],'organized_path':str(dest),'sha256':d['sha256'],'original_preserved':True})
        c.execute('INSERT OR REPLACE INTO document_files VALUES(?,?,?,1)',(str(dest),d['document_id'],d['sha256']))
        c.execute('INSERT OR REPLACE INTO catalog_documents VALUES(?,?,?,?,?,?,?,?)',(d['document_id'],cat,json.dumps(tags,ensure_ascii=False),display,str(old),str(dest),d['sha256'],json.dumps(basis,ensure_ascii=False)))
        meta.setdefault('pre_catalog_primary_path',str(old));meta['primary_path']=str(dest);meta['catalog_path']=str(dest);meta['catalog_category']=cat;meta['catalog_species_tag']=fish;meta['classification_is_not_applicability_verification']=True
        c.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',(json.dumps(meta,ensure_ascii=False),d['document_id']))
        docs.append({'document_id':d['document_id'],'title':display,'category':cat,'species_tag':fish,'species_mentions':tags,'source_version':d['source_version'],'publisher':d['publisher'],'sha256':d['sha256'],'original_path':str(old),'organized_path':str(dest),'classification_basis':basis,'parse_status':d['parse_status']})
    # Every registered source points to an organized original or to an exact,
    # separately preserved finite fact/source sidecar, never a guessed PDF.
    extras=[]
    for s in source_rows:
        dest=canonical.get(s['source_sha256'])
        source=Path(s['source_file']) if s['source_file'] else None
        if dest is None and source and source.is_file():
            dest=overview/'來源使用與證據紀錄'/safe_name(s['source_id'])/source.name;copy_checked(source,dest)
            extras.append({'source_id':s['source_id'],'original_path':str(source),'organized_path':str(dest),'sha256':sha(dest),'role':'EXISTING_REGISTERED_FINITE_SOURCE_RECORD_NOT_AUTOMATIC_FULLTEXT_EXPANSION'})
        if dest:
            c.execute('UPDATE sources SET source_file=? WHERE source_id=?',(str(dest),s['source_id']));c.execute('UPDATE chunks SET source_path=? WHERE source_id=?',(str(dest),s['source_id']))
    c.commit();emit({'stage':'catalog_originals','originals':len(docs),'source_sidecars':len(extras)})
    media=[]
    for idx,a in enumerate(c.execute('SELECT * FROM media_assets ORDER BY asset_id').fetchall(),1):
        linked=[dict(x) for x in c.execute('SELECT DISTINCT document_id,page,kind FROM document_elements WHERE asset_id=?',(a['asset_id'],))]
        docid=linked[0]['document_id'] if linked else None;cat,fish,title=classification.get(docid,('08_未分類與待核對','來源待核','未綁定文件'))
        extension=Path(a['path']).suffix.lower() or '.png'
        dest=lib/'09_圖片與表格'/'01_圖片'/fish/(safe_name(title,45)+'__'+str(docid or 'UNKNOWN')[-8:])/(a['sha256']+extension)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():dest.write_bytes(a['raw_bytes'])
        if sha(dest)!=a['sha256']:raise ValueError('Image copy mismatch: '+str(dest))
        c.execute('INSERT OR REPLACE INTO catalog_assets VALUES(?,?,?)',(a['asset_id'],str(dest),a['sha256']));c.execute('UPDATE media_assets SET path=? WHERE asset_id=?',(str(dest),a['asset_id']))
        media.append({'asset_id':a['asset_id'],'sha256':a['sha256'],'organized_path':str(dest),'source_positions':linked,'ocr_status':a['ocr_status'],'has_text':bool(a['ocr_text']),'width':a['width'],'height':a['height'],'not_expert_visual_verification':True})
        if idx%1000==0:c.commit();emit({'stage':'catalog_images','completed':idx})
    tables=[]
    for row in c.execute("SELECT * FROM document_elements WHERE kind='TABLE'").fetchall():
        meta=json.loads(row['metadata_json']);cells=meta.get('cells',[]);cat,fish,title=classification[row['document_id']]
        folder=lib/'09_圖片與表格'/'02_表格'/fish/(safe_name(title,45)+'__'+row['document_id'][-8:]);folder.mkdir(parents=True,exist_ok=True)
        dest=folder/(row['element_id']+'.csv')
        with dest.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows([['' if cell is None else cell for cell in line] for line in cells])
        detail={'element_id':row['element_id'],'document_id':row['document_id'],'physical_page':row['page'],'bbox':json.loads(row['bbox_json']),'original_text':row['text'],'native_cells':cells,'metadata':meta,'csv_path':str(dest),'blank_not_zero':True,'merged_headers_not_guessed':True,'image_asset_id':row['asset_id']}
        dump(dest.with_suffix('.json'),detail);tables.append({k:v for k,v in detail.items() if k not in ('metadata','native_cells','original_text')})
    c.commit()
    # Export the precise cleaned/segmented text with its source position and
    # quality status. These exports are provenance artifacts, not extra facts.
    for doc in docs:
        cat,fish,title=classification[doc['document_id']]
        folder=lib/'10_清洗文字與語義片段'/cat/fish;folder.mkdir(parents=True,exist_ok=True)
        units=[dict(x) for x in c.execute('SELECT unit_id,kind,locator,text,content_sha256,related_chunk_id FROM archive_units WHERE document_id=? ORDER BY unit_id',(doc['document_id'],))]
        lines(folder/(safe_name(title,65)+'__'+doc['document_id'][-8:]+'.jsonl'),units)
    for item in read(r/'incomplete_downloads.json'):
        source=Path(item['path']);dest=lib/'99_待補件_下載失敗'/source.name;copy_checked(source,dest,item['sha256']);item['organized_path']=str(dest)
    lines(overview/'原始文件分類清單.jsonl',docs);lines(overview/'原始路徑對照.jsonl',pathmap);lines(overview/'圖片來源與頁碼.jsonl',media);lines(overview/'表格來源與頁碼.jsonl',tables);lines(overview/'其他來源紀錄.jsonl',extras)
    current_sources=[dict(x) for x in c.execute('SELECT source_id,dataset_id,title,publisher,source_file,source_sha256,owner_admission_status,license_scope_status,version_status,processing_scope,source_cluster_id FROM sources')]
    lines(overview/'RAG來源登錄.jsonl',current_sources)
    lines(r/'organized_originals.jsonl',docs);lines(r/'organized_media.jsonl',media);lines(r/'organized_tables.jsonl',tables)
    dump(r/'catalog_summary.json',{'directory':str(lib),'originals':len(docs),'sources':len(current_sources),'images':len(media),'tables':len(tables),'categories':dict(collections.Counter(d['category'] for d in docs)),'source_sidecars':len(extras),'originals_moved_or_deleted':False})
    rows=''.join('<tr><td>'+html.escape(d['category'])+'</td><td>'+html.escape(d['species_tag'])+'</td><td><a href="'+html.escape(Path(d['organized_path']).relative_to(lib).as_posix(),quote=True)+'">'+html.escape(d['title'])+'</a></td><td>'+html.escape(d['source_version'] or '原件版本待核')+'</td><td>'+html.escape(d['document_id'])+'</td></tr>' for d in docs)
    index='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAG來源資料總庫</title><style>body{font-family:Microsoft JhengHei,sans-serif;margin:30px;background:#f2f8fc;color:#17364b}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border:1px solid #d5e7f0;text-align:left}input{padding:12px;width:95%;margin:14px 0}a{color:#086b9a}code{overflow-wrap:anywhere}</style><h1>RAG來源資料總庫</h1><p>原始文件 '+str(len(docs))+' 份；圖片 '+str(len(media))+' 份；原生表格 '+str(len(tables))+' 個。原位置保留，按 SHA 去重集中複製。</p><p>資料整理分類不代表已核驗所有魚種適用性。OCR、歷史法規與用藥資料仍保留原有版本和使用限制；失敗下載在 99_待補件_下載失敗。</p><input id="q" placeholder="搜尋名稱、分類、魚種或版本"><table><thead><tr><th>分類</th><th>魚種標記</th><th>原始文件</th><th>版本</th><th>文件ID</th></tr></thead><tbody>'+rows+'</tbody></table><script>document.getElementById("q").oninput=function(){for(const row of document.querySelectorAll("tbody tr")){row.hidden=!row.textContent.toLowerCase().includes(this.value.toLowerCase())}}</script></html>'
    (lib/'開啟來源資料總覽.html').write_text(index,encoding='utf-8')
    (lib/'閱讀說明.txt').write_text('RAG來源資料總庫\n原始資料集中複製，既有位置保留，不刪除或移動歷史資料。\n00_資料總覽：來源、分類、SHA及原始路徑。\n01_官方法規與附件／02_歷史法規與修正說明／03_養殖技術與問答／04_疾病與生物安全／05_水質環境與氣候／06_用藥許可與殘留資料／07_統計與名稱代碼。\n09_圖片與表格：圖片原始bytes與CSV/JSON表格，位置見00的對照清單。\n10_清洗文字與語義片段：清洗切分文字、來源定位與片段ID。\n99_待補件_下載失敗：損壞壓縮檔保留，不當作成功資料入庫。\n分類只供整理，不能替代專業適用性判斷。所有原有署名、授權、版本和魚種條件仍適用。\nDGBAS 2020僅單年度描述性事實；無年度統計不補造年度；藥品許可不推算用量或停藥期。\n',encoding='utf-8')
    c.close();emit({'stage':'catalog_complete','originals':len(docs),'images':len(media),'tables':len(tables),'directory':str(lib)})

def init_arg():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['init','inventory','ocr','vectors','catalog']);return p.parse_args()

if __name__=='__main__':
    a=init_arg();{'init':init,'inventory':inventory,'ocr':media_ocr,'vectors':vectors,'catalog':catalog}[a.stage]()
