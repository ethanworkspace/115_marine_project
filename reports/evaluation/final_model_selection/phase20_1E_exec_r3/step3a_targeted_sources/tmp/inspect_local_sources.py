import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,r'C:\my project\115_marine_project\.venv\Lib\site-packages')
import fitz
root=Path(r'C:\my project\115_marine_project')
paths=list((root/'data/recovery/raw_sources').glob('*'))
terms=['石斑','金目鱸','鱸魚','鱸','吳郭','虱目','烏魚','鰻','使用對象','附表','品目','停藥期','水產動物']
for p in paths:
    if p.suffix.lower()!='.pdf': continue
    b=p.read_bytes(); doc=fitz.open(stream=b,filetype='pdf')
    pages=[]
    for n,page in enumerate(doc,1):
      tx=page.get_text()
      hits=[t for t in terms if t in tx]
      if hits: pages.append({'page':n,'terms':hits,'excerpt':tx[:1500]})
    print(json.dumps({'file':p.name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'pages':len(doc),'hits':pages[:25]},ensure_ascii=True))
# manifest records for the two existing official law docs and fish manuals
for mp in [root/'data/recovery/document_manifest_v3.jsonl',root/'reports/recovery/document_manifest_v3.jsonl']:
 if mp.exists():
  print('MANIFEST',str(mp))
  for line in mp.open(encoding='utf-8'):
   if any(s in line for s in ['FL035443','FL014718','技術手冊17','疾病防治','防寒']): print(line[:2500])
