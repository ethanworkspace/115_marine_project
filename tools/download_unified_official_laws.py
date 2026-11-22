"""Normal official HTTPS acquisition; validate pages and preserve real bytes."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import hashlib,json,re,urllib.parse,requests
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'research_staging/unified_rag_v5_build_pointer.json').read_text(encoding='utf-8'))
W=Path(P['workspace']);R=Path(P['report_directory'])
catalog=[
 ('M0130003','動物傳染病防治條例','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0130003'),
 ('M0130015','動物用藥品管理法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0130015'),
 ('M0130023','動物用藥品使用準則','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0130023'),
 ('J0110001','水利法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0110001'),
 ('O0040001','水污染防治法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=O0040001'),
 ('M0050001','漁業法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0050001'),
 ('O0060020','環境用藥微生物製劑使用於生態及水源保育或保護區運作管理辦法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=O0060020'),
 ('M0050070','養殖漁業生產區設置及管理準則','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0050070'),
 ('M0090019','農業天然災害救助辦法','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0090019'),
 ('D0060013','非都市土地使用管制規則','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013'),
 ('L0040026','動物用藥殘留標準','https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040026'),
 ('GL002203','一百十五年度循環水養殖設施補助要點','https://law.moa.gov.tw/LawContent.aspx?id=GL002203'),
]
session=requests.Session();session.headers['User-Agent']='MarineResearch-SourceVerification/1.0'
out=[];oldpath=W/'official_laws/download_manifest.json'
if oldpath.exists():out=json.loads(oldpath.read_text(encoding='utf-8'))
def save_manifest():
    oldpath.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    (R/'official_law_download_manifest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
def acquire(ident,title,url,path,kind='PAGE',parent=None):
    previous=next((x for x in out if x.get('url')==url and x.get('status')=='SAVED'),None)
    if previous and Path(previous['path']).is_file():return previous
    row={'law_id':ident,'expected_title':title,'url':url,'kind':kind,'parent_url':parent,
         'obtained_at':datetime.now(timezone(timedelta(hours=8))).isoformat()}
    try:
        response=session.get(url,timeout=(15,70));response.raise_for_status();raw=response.content
        if not raw:raise ValueError('EMPTY_RESPONSE')
        if kind=='PAGE':
            response.encoding=response.apparent_encoding or 'utf-8';soup=BeautifulSoup(response.text,'html.parser');text=soup.get_text(' ',strip=True)
            if title not in text or len(text)<200:raise ValueError('EXPECTED_LAW_NOT_PRESENT_IN_RESPONSE')
        elif not raw.startswith(b'%PDF'):raise ValueError('NOT_PDF_BYTES')
        path.write_bytes(raw);row.update(status='SAVED',path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),http_status=response.status_code,final_url=response.url,content_type=response.headers.get('Content-Type'))
    except Exception as exc:row.update(status='DOWNLOAD_ERROR',error=repr(exc))
    out.append(row);save_manifest();print(json.dumps(row,ensure_ascii=False),flush=True);return row
for ident,title,url in catalog:
    row=acquire(ident,title,url,W/'official_laws'/(ident+'.html'))
    if row['status']!='SAVED':continue
    raw=Path(row['path']).read_bytes();soup=BeautifulSoup(raw,'html.parser')
    seen=set()
    for a in soup.find_all('a',href=True):
        label=a.get_text(' ',strip=True);href=urllib.parse.urljoin(url,a['href']);host=urllib.parse.urlparse(href).hostname
        if host not in ('law.moj.gov.tw','law.moa.gov.tw') or href in seen:continue
        if not (re.search(r'附件|附表|完整條文|全文|行政院公報',label) and ('.pdf' in href.lower() or 'file' in href.lower())):continue
        if any(x in label for x in ['DOC','ODT','.doc','.odt']):continue
        seen.add(href);key=hashlib.sha256(href.encode()).hexdigest()[:12]
        acquire(ident,label,href,W/'official_laws'/(ident+'-'+key+'.pdf'),kind='ATTACHMENT',parent=url)
save_manifest()
