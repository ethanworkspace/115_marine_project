import collections, hashlib, json, math, pathlib, re, unicodedata
from pypdf import PdfReader

ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_i_20261014_195032'
RUN=ROOT/'reports/evaluation/fish_test_run_20261012_152244'
H=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
def jl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def norm(s): return unicodedata.normalize('NFKC',s or '').casefold()
def bigrams(s):
 s=norm(s); chars=[c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P')]
 return collections.Counter(''.join(chars[i:i+2]) for i in range(max(0,len(chars)-1)))
def score(qgrams,tgrams):
 return sum(min(n,tgrams[g]) for g,n in qgrams.items())
questions={r['question_id']:r for r in jl(RUN/'fish_test_questions_normalized.jsonl')}
maps={r['question_id']:r for r in jl(H/'source_mapping_recovery_180.jsonl')}
sources={}
for qid,r in maps.items():
 for f in r.get('local_originals') or []:
  if f.get('exists') and f.get('checksum_match'):
   sources.setdefault(f['path'],{'sha256':f['actual_sha256'],'source_url':f.get('source_url'),'version':f.get('version'),'questions':[]})['questions'].append(qid)
integrity=[]; pagecache={}
for rel,meta in sources.items():
 p=ROOT/rel
 reader=PdfReader(str(p), strict=False)
 pages=[]
 for i,page in enumerate(reader.pages,1):
  txt=page.extract_text() or ''
  pages.append(txt)
 pagecache[rel]=pages
 integrity.append({'path':rel,'exists':p.is_file(),'actual_sha256':sha(p),'expected_sha256':meta['sha256'],'checksum_match':sha(p)==meta['sha256'],
                   'file_size':p.stat().st_size,'pdf_pages':len(reader.pages),'encrypted':reader.is_encrypted,
                   'pages_with_extractable_text':sum(bool(x.strip()) for x in pages),'total_extracted_chars':sum(len(x) for x in pages),
                   'text_page_sha256':[hashlib.sha256(x.encode('utf-8')).hexdigest() for x in pages]})
OUT.joinpath('local_source_pdf_integrity.json').write_text(json.dumps({'files':integrity,'distinct_files':len(integrity)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
reviews=[]
for qid,r in maps.items():
 local=[f for f in r.get('local_originals') or [] if f.get('exists') and f.get('checksum_match')]
 if not local: continue
 q=questions[qid]
 qgrams=bigrams((q.get('question_text') or '')+' '+(q.get('candidate_reference_answer') or ''))
 for f in local:
  pages=pagecache[f['path']]
  ranked=sorted(((score(qgrams,bigrams(t)),i,t) for i,t in enumerate(pages,1)),reverse=True)[:4]
  quotes=[]
  for sc,pg,txt in ranked:
   if not txt.strip(): continue
   compact=re.sub(r'\s+',' ',txt).strip()
   quotes.append({'page':pg,'retrieval_overlap_score':sc,'page_characters':len(txt),'text_excerpt':compact[:900]})
  reviews.append({'question_id':qid,'question_text':q.get('question_text'),'candidate_reference_answer':q.get('candidate_reference_answer'),
                  'species':q.get('species_chinese'),'category':q.get('inferred_category'),'source_path':f['path'],'source_sha256':f.get('actual_sha256'),
                  'source_url':f.get('source_url'),'source_version':f.get('version'),'candidate_pages':quotes})
with OUT.joinpath('local_source_question_page_candidates.jsonl').open('w',encoding='utf-8',newline='\n') as f:
 for r in reviews: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
print(json.dumps({'local_source_files':len(integrity),'question_source_pairs':len(reviews),'files':integrity},ensure_ascii=False,indent=2))
