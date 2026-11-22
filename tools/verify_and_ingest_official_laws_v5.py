"""Verify statutory snapshots and separate current wording from old explanations."""
import argparse,difflib,json,re,shutil,sqlite3,sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
from src.unified_rag_v4.common import clean,digest,dump,sha_file
from src.unified_rag_v4.extraction import add_element,extract_pdf,WindowsOCR
from src.unified_rag_v4.segmentation import segment_document

def norm(text):return re.sub(r'\s+','',text)
def parse_law(row):
    soup=BeautifulSoup(Path(row['path']).read_bytes(),'html.parser')
    meta={}
    for tr in soup.select('tr'):
        cells=tr.find_all(['th','td'],recursive=False)
        if len(cells)>=2:
            key=cells[0].get_text(' ',strip=True).rstrip('：:');meta[key]=cells[1].get_text(' ',strip=True)
    articles=[]
    for block in soup.select('.law-reg-content .row'):
        no=block.select_one('.col-no');body=block.select_one('.col-data')
        if no and body:
            anchor=no.select_one('a')
            ident=clean((anchor or no).get_text(' ',strip=True));text=clean(body.get_text('\n',strip=True))
            if re.match(r'^第\s*\d',ident):articles.append({'article':ident,'body':text,'exact_text':ident+'\n'+text,'locator':'.law-reg-content .row / '+ident})
    if not articles:
        body=soup.select_one('.law-content')
        if not body:raise ValueError('NO_OFFICIAL_ARTICLE_BODY')
        text=clean(body.get_text('\n',strip=True))
        parts=re.split(r'(?m)(?=^[一二三四五六七八九十]+、)',text)
        for i,part in enumerate(parts,1):
            if part.strip():articles.append({'article':'要點段落'+str(i),'body':part,'exact_text':part,'locator':'.law-content paragraph '+str(i)})
    fulltext=soup.get_text(' ',strip=True)
    cutoff=re.search(r'法規整編資料截止日[：:\s]*民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日',fulltext)
    return {'law_id':row['law_id'],'title':meta.get('法規名稱',row['expected_title']),
        'official_version':meta.get('修正日期',meta.get('公發布日',meta.get('發布日期','未列明'))),
        'official_compilation_cutoff':cutoff.group(0) if cutoff else None,
        'official_metadata':meta,'articles':articles,'source':row,
        'organization_transfer_notice':next((t.get_text(' ',strip=True) for t in soup.select('.ld-ann') if '112' in t.get_text()),None)}

def local_articles(text):
    parts=re.split(r'(?m)^第\s*(\d+(?:\s*[-－]\s*\d+)?)\s*條\s*$',text)
    out={}
    for i in range(1,len(parts)-1,2):out[re.sub(r'\s','',parts[i]).replace('－','-')]=parts[i+1]
    return out

def add_atomic_official_articles(con,source,rec):
    for row in con.execute("SELECT * FROM document_elements WHERE document_id=? AND kind IN ('PARAGRAPH','LAW_METADATA') ORDER BY rowid",(rec['document_id'],)).fetchall():
        meta=json.loads(row['metadata_json']);text=row['text']
        unit={'segment_id':'SEG-LAW-'+digest([rec['document_id'],row['element_id'],text])[:24],
            'elements':[row['element_id']],'text':text,'page_start':None,'page_end':None,
            'section':meta.get('article','官方條文'),'kind':'TEXT',
            'quality':'NATIVE_TEXT_LAYOUT_BOUND' if len(text)<=4000 else 'OVERSIZE_UNIT_REVIEW',
            'method':'OFFICIAL_ARTICLE_ATOMIC_NO_CROSS_ARTICLE_MERGE'}
        con.execute('INSERT OR IGNORE INTO element_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)',(unit['segment_id'],rec['document_id'],json.dumps(unit['elements']),unit['kind'],text,None,None,unit['section'],unit['method'],unit['quality'],None))
        x.b.add_segment_chunk(con,source,rec,unit)

def add_law_metadata(con,did,law,sha):
    fields={key:value for key,value in law['official_metadata'].items() if key in ('法規名稱','修正日期','公發布日','發布日期','發文字號','法規類別','法規體系')}
    text='\n'.join(key+'：'+value for key,value in fields.items())
    if law.get('official_compilation_cutoff'):text+='\n'+law['official_compilation_cutoff']
    if law.get('organization_transfer_notice'):text+='\n'+law['organization_transfer_notice']
    add_element(con,did,None,'LAW_METADATA',text,metadata={'article':'官方版本資訊','official_dom_locator':'Official page table metadata cells and compilation/organization notice','source_sha256':sha,'native_fields':fields},ordinal=9999)

def analyze():
    downloads=json.loads((x.W/'official_laws/download_manifest.json').read_text(encoding='utf-8'))
    pages=[r for r in downloads if r['kind']=='PAGE' and r['status']=='SAVED']
    laws={row['law_id']:parse_law(row) for row in pages}
    parent=sqlite3.connect(Path(x.CFG['parent_database']).as_uri()+'?mode=ro',uri=True);parent.row_factory=sqlite3.Row
    reviews=[]
    for did,ident in x.LAW_DOCS.items():
        doc=parent.execute('SELECT * FROM documents WHERE document_id=?',(did,)).fetchone()
        if not doc:continue
        rec=json.loads(doc['metadata_json']);text='\n'.join(r[0] for r in parent.execute('SELECT cleaned_text FROM document_pages WHERE document_id=? ORDER BY page',(did,)))
        if not text:text='\n'.join(r[0] for r in parent.execute('SELECT text FROM document_elements WHERE document_id=?',(did,)))
        original_version=re.search(r'(?:修正日期|公布日期|發布日期)[：:\s]*(民國\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)',text)
        law=laws.get(ident);local=local_articles(text);comp=[]
        if law:
            for article in law['articles']:
                key=re.sub(r'第|條|\s','',article['article'])
                if key not in local:continue
                a=norm(local[key]);b=norm(article['body']);same=a==b
                comp.append({'article':article['article'],'status':'NORMALIZED_TEXT_MATCH' if same else 'TEXT_OR_LAYOUT_DIFFERENCE_REQUIRES_REVIEW',
                    'local_text':local[key],'official_text':article['body'],
                    'official_locator':article['locator'],'similarity_for_triage_only':difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()})
        exact_resources=[r for r in downloads if r.get('sha256')==doc['sha256'] and r['kind']=='ATTACHMENT' and r['status']=='SAVED']
        explanation=bool(re.search('總說明|逐條說明|修正條文對照表|修正對照表',text[:250]))
        date_match=bool(law and original_version and norm(original_version.group(1))==norm(law['official_version']))
        status='EXPLANATION_OR_COMPARISON_NOT_CURRENT_NORMATIVE_TEXT' if explanation else 'OFFICIAL_ATTACHMENT_BYTES_MATCH' if exact_resources else 'VERSION_DATE_DIFFERS' if law and original_version and not date_match else 'VERSION_DATE_MATCH_TEXT_CHECK_RECORDED' if date_match else 'VERSION_NOT_FULLY_ESTABLISHED'
        if date_match and comp and all(r['status']=='NORMALIZED_TEXT_MATCH' for r in comp) and len(comp)==len(law['articles']):status='OFFICIAL_DATE_AND_ALL_ARTICLES_MATCH'
        reviews.append({'document_id':did,'title':doc['title'],'law_id':ident,'original_sha256':doc['sha256'],
            'original_version':original_version.group(1) if original_version else None,'official_version':law['official_version'] if law else None,
            'official_url':law['source']['url'] if law else None,'verification_status':status,
            'date_matches':date_match,'local_article_n':len(local),'compared_articles':len(comp),
            'matching_articles':sum(r['status']=='NORMALIZED_TEXT_MATCH' for r in comp),'article_comparisons':comp,
            'matching_official_resources':exact_resources,'not_legal_advice':True,'not_approval_of_drug_dose_or_withdrawal':True})
    parent.close();dump(x.R/'official_laws_parsed.json',laws);dump(x.R/'local_law_version_comparison.json',reviews)
    with (x.R/'law_review_by_document.jsonl').open('w',encoding='utf-8') as f:
        for r in reviews:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    print(json.dumps({'official_law_pages':len(laws),'local_documents_compared':len(reviews),'date_differences':[r['title'] for r in reviews if r['verification_status']=='VERSION_DATE_DIFFERS']},ensure_ascii=False))

def ingest():
    laws=json.loads((x.R/'official_laws_parsed.json').read_text(encoding='utf-8'))
    reviews=json.loads((x.R/'local_law_version_comparison.json').read_text(encoding='utf-8'))
    downloads=json.loads((x.W/'official_laws/download_manifest.json').read_text(encoding='utf-8'))
    con=x.connect();con.execute('CREATE TABLE IF NOT EXISTS law_source_status(document_id TEXT PRIMARY KEY,law_id TEXT,status TEXT,metadata_json TEXT)')
    for row in reviews:con.execute('INSERT OR REPLACE INTO law_source_status VALUES(?,?,?,?)',(row['document_id'],row['law_id'],row['verification_status'],json.dumps(row,ensure_ascii=False)))
    con.commit();ocr=None
    for row in downloads:
        if row['status']!='SAVED':continue
        path=Path(row['path']);sha=sha_file(path);existing=con.execute('SELECT document_id FROM documents WHERE sha256=?',(sha,)).fetchone()
        did=existing[0] if existing else 'DOC-'+sha[:20];law=laws[row['law_id']]
        status='OFFICIAL_LATEST_AVAILABLE_PAGE_SNAPSHOT' if row['kind']=='PAGE' else 'OFFICIAL_ATTACHMENT_BYTES_MATCH'
        details={'resource':row,'law_id':row['law_id'],'official_version':law['official_version'],'compilation_cutoff':law['official_compilation_cutoff'],
            'organization_transfer_notice':law['organization_transfer_notice'],'not_certification_of_all_later_amendments':True,
            'not_individual_drug_prescription':True}
        con.execute('INSERT OR REPLACE INTO law_source_status VALUES(?,?,?,?)',(did,row['law_id'],status,json.dumps(details,ensure_ascii=False)))
        if existing:
            con.execute('INSERT OR IGNORE INTO document_files VALUES(?,?,?,0)',(str(path),did,sha))
            if row['kind']=='PAGE':
                old=con.execute('SELECT metadata_json FROM documents WHERE document_id=?',(did,)).fetchone()
                rec=json.loads(old[0]);rec['official_law_snapshot']=details
                for unit in con.execute('SELECT segment_id,chunk_id FROM element_chunks WHERE document_id=?',(did,)).fetchall():
                    if unit['chunk_id']:
                        con.execute('DELETE FROM chunks WHERE chunk_id=?',(unit['chunk_id'],));con.execute('DELETE FROM source_records WHERE source_record_id=?',(unit['segment_id'],));con.execute('DELETE FROM answer_eligibility WHERE chunk_id=?',(unit['chunk_id'],))
                con.execute('DELETE FROM element_chunks WHERE document_id=?',(did,));con.execute('DELETE FROM document_elements WHERE document_id=?',(did,));con.execute('DELETE FROM semantic_boundaries WHERE document_id=?',(did,))
                for i,article in enumerate(law['articles']):add_element(con,did,None,'PARAGRAPH',article['exact_text'],metadata={'law_id':row['law_id'],'article':article['article'],'official_dom_locator':article['locator'],'source_sha256':sha},ordinal=i)
                add_law_metadata(con,did,law,sha)
                source=x.b.register_source(con,rec)
                add_atomic_official_articles(con,source,rec)
                con.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',(json.dumps(rec,ensure_ascii=False),did))
            con.commit();continue
        title=law['title']+(' / '+row['expected_title'] if row['kind']=='ATTACHMENT' else '')
        rec={'document_id':did,'sha256':sha,'paths':[str(path)],'primary_path':str(path),'parse_path':str(path),'suffix':path.suffix,
            'first_page':title,'publication_excerpt':title+'\n'+law['official_version'],'rights_statements':[],
            'native_record_version':'官方版本：'+law['official_version']+'；取得時間：'+row['obtained_at']+'；整編截止：'+str(law['official_compilation_cutoff']),
            'owner_decision':'USER_REQUEST_OFFICIAL_LAW_VERIFICATION','usage_policy':{'status':'OFFICIAL_STATUTORY_SNAPSHOT_ART9',
                'eligible':True,'url':row['url'],'license_url':'https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070017',
                'publisher':'法務部全國法規資料庫及原發布主管機關' if 'moj.gov' in row['url'] else '農業部',
                'scope':'Official statutory wording and exact attachment snapshot only; preserve version, compilation cutoff, species and prescription conditions. Explanatory or historical documents are separate.',
                'general_scope':True,'evidence':['Official HTTPS bytes saved; title and article body verified; attachment identity bound to official parent page']},
            'official_law_snapshot':details,'user_use_attestation':x.CFG['user_use_attestation']}
        snapshot=x.W/'snapshots'/(sha+path.suffix);shutil.copyfile(path,snapshot)
        con.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)',(did,sha,title,path.suffix,rec['usage_policy']['publisher'],rec['native_record_version'],'OFFICIAL_STATUTORY_SNAPSHOT_ART9','USER_REQUEST_OFFICIAL_LAW_VERIFICATION','PROCESSING',json.dumps(rec,ensure_ascii=False)))
        con.execute('INSERT INTO document_files VALUES(?,?,?,0)',(str(path),did,sha));con.execute('INSERT INTO raw_documents VALUES(?,?)',(did,path.read_bytes()));con.commit()
        if row['kind']=='PAGE':
            for i,article in enumerate(law['articles']):add_element(con,did,None,'PARAGRAPH',article['exact_text'],metadata={'law_id':row['law_id'],'article':article['article'],'official_dom_locator':article['locator'],'source_sha256':sha},ordinal=i)
            add_law_metadata(con,did,law,sha)
        else:
            if ocr is None:ocr=WindowsOCR(ROOT,x.W)
            rec['extraction_result']=extract_pdf(con,rec,x.W,ocr)
        source=x.b.register_source(con,rec)
        if row['kind']=='PAGE':add_atomic_official_articles(con,source,rec)
        else:
            for unit in segment_document(con,did,semantic=False):x.b.add_segment_chunk(con,source,rec,unit)
        con.execute('UPDATE documents SET parse_status=?,metadata_json=? WHERE document_id=?',('PARSED',json.dumps(rec,ensure_ascii=False),did));con.commit()
        print(json.dumps({'stage':'OFFICIAL_LAW_INGEST','title':title,'kind':row['kind']},ensure_ascii=False),flush=True)
    if ocr:ocr.close()
    # Original law versions remain searchable, but not as default current advice.
    for row in con.execute('SELECT c.chunk_id,c.restrictions_json,d.document_id FROM chunks c JOIN documents d ON c.source_sha256=d.sha256').fetchall():
        law=con.execute('SELECT * FROM law_source_status WHERE document_id=?',(row['document_id'],)).fetchone()
        if law:
            restrictions=json.loads(row['restrictions_json']);restrictions['law_source_status']={k:law[k] for k in ('law_id','status')}
            con.execute('UPDATE chunks SET restrictions_json=? WHERE chunk_id=?',(json.dumps(restrictions,ensure_ascii=False),row['chunk_id']))
    con.commit();con.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['analyze','ingest']);a=p.parse_args();{'analyze':analyze,'ingest':ingest}[a.stage]()
