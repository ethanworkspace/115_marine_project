import json,hashlib,re
from pathlib import Path
import fitz
root=Path(r'C:\my project\115_marine_project')
base=root/'reports/evaluation/final_model_selection/phase20_1E_exec_r3'
inp=base/'step3a_targeted_sources/staged_evidence_candidates.jsonl'
corpus=root/'data/evaluation/corpus_v2.jsonl'
paths={
 'bd7647d8-f4af-5987-982a-1c7c6fb252af':'my_data/my_data/養殖魚類疾病防治 .pdf',
 '30b9fedc-1646-50b0-b7f0-0aeb9f54a76a':'my_data/my_data/養殖漁業防寒須知(農業部漁業署).pdf',
 '6a46f128-54ac-57aa-b7c7-9f138b08b0f4':'my_data/my_data/水產研究16(2)吳郭魚雜交與自交系的成長比較－快速成長品系之研發.pdf.pdf',
 '8f337c28-890f-5ddb-9d92-612427284c4f':'my_data/my_data/技術手冊17-漁電共生養殖技術應用手冊(下).pdf',
 '6fc2b60d-9aa8-5036-8495-6f4517fc3404':'data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf',
 '91004909-0be2-5a31-b034-c65931336886':'my_data/my_data/07鰻魚養殖要點及池塘清理消毒.pdf.pdf'}
needles={
 'chunk_143bc4f1205156c38fafb48a9250e76b':['虱目魚等均會遭受侵害'],
 'chunk_1b8be225a69a51eab7cfe79366276df0':['不適合冬季養殖之熱帶魚種','虱目魚'],
 'chunk_591b5e4b41885582a5c63fb2b92570aa':['越冬期','低溫適應性'],
 'chunk_731052d8f6f35845949a190a4efd2b60':['石斑魚','常見的疾病'],
 'chunk_4dd88188fe6951b9bb22626ad1e20abc':['鱸形目','金目鱸'],
 'chunk_17b09aacb4685829b42c4ca1c2882021':['目前烏魚養殖常見之疾病'],
 'chunk_22b9e2d6b62b584ba72d5ca49b776c61':['Anguilla japonica','最適合生長的水溫']}
def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
rows={}
for ln in corpus.open(encoding='utf-8'):
 try:
  o=json.loads(ln); rows[o.get('chunk_id')]=o
 except Exception: pass
candidates=[json.loads(x) for x in inp.read_text(encoding='utf-8').splitlines() if x.strip()]
out=[]
for c in candidates:
 cid=c.get('chunk_id'); row=rows.get(cid); did=c.get('document_id'); p=paths.get(did); p=root/p if p else None
 r={'candidate_id':c['candidate_id'],'species':c['species'],'category':c['category'],'chunk_id':cid or None,'document_id':did,'chunk_exists':row is not None,'chunk_document_match':bool(row and row.get('document_id')==did),'page':c.get('page'),'pdf_path':str(p) if p else None,'pdf_exists':bool(p and p.exists()),'pdf_open':False,'pdf_page_count':None,'pdf_sha256':None,'expected_source_sha256':c.get('source_checksum'),'pdf_sha256_match':None,'span_page':None,'span_file_checksum_match':None,'support_text_match':None,'support_text_checks':[],'pdf_error':None}
 if row:
  spans=row.get('source_spans') or []
  r['span_page']=spans[0].get('page_number') if spans else row.get('page_start')
  r['span_file_checksum']=spans[0].get('file_checksum') if spans else None
 if p and p.exists():
  r['pdf_sha256']=digest(p); r['pdf_sha256_match']=bool(c.get('source_checksum') and r['pdf_sha256']==c.get('source_checksum'))
  try:
   d=fitz.open(p); r['pdf_open']=True;r['pdf_page_count']=len(d)
   page_no=r['span_page'] or c.get('page')
   if page_no and 1<=int(page_no)<=len(d):
    txt=d[int(page_no)-1].get_text(); norm=re.sub(r'\s+','',txt)
    target=needles.get(cid,[]); r['support_text_checks']=[{'text':n,'found':re.sub(r'\s+','',n) in norm} for n in target]; r['support_text_match']=bool(target) and all(x['found'] for x in r['support_text_checks'])
   r['span_file_checksum_match']=bool(spans and r['span_file_checksum']==r['pdf_sha256'])
   d.close()
  except Exception as e:r['pdf_error']=type(e).__name__+': '+str(e)
 r['corpus_source_checksum']=row.get('source_checksum') if row else None
 r['corpus_source_checksum_matches_pdf']=bool(row and r['pdf_sha256'] and row.get('source_checksum')==r['pdf_sha256'])
 r['source_identity_status']=row.get('source_verification_status') if row else 'no_exact_chunk_mapping'
 r['source_title']=c.get('source_title')
 r['decision']='needs_review'
 r['reason']='Audit provenance and PDF content; keyword hit alone is insufficient.'
 out.append(r)
output=base/'step3b_source_review/tmp/local_candidate_verification.jsonl'
output.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in out),encoding='utf-8')
print(json.dumps({'rows':len(out),'output':str(output),'checks':out},ensure_ascii=False,indent=2))
