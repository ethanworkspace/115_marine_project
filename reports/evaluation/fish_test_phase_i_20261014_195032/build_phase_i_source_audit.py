from __future__ import annotations
import datetime as dt, hashlib, json, pathlib, re, sys
from pypdf import PdfReader

ROOT=pathlib.Path.cwd()
OUT=ROOT/'reports/evaluation/fish_test_phase_i_20261014_195032'
H=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
NOW=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
MAP=H/'source_mapping_recovery_180.jsonl'
LOCAL_DOCS=OUT/'source_documents_29_mapping.jsonl'
LOCAL_CAND=OUT/'local_source_question_page_candidates.jsonl'
URL_READABLE={
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16309&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16311&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16337&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16340&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16560',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16566',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=16567',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=1815',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=21795',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=50865&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=52014&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=62162&print=Y',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=65549',
 'https://kmweb.moa.gov.tw/subject/subject.php?id=65550',
 'https://law.moa.gov.tw/LawContent.aspx?id=FL014718&media=print',
 'https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print',
 'https://www.fa.gov.tw/view.php?id=12&print=Y&theme=FisheriesAct_LAW',
 'https://www.fa.gov.tw/view.php?id=385&print=Y&subtheme=&theme=web_structure',
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=4gUVSnLKWGPlusHT9kGrI1RL8iMEeeY3OXhx7TzM0yoVvYYz44GTkGXZi1lSqnrCa4RMOY0Jzgg8W2AWGEqualWGEqualprOXeeU6O15DgFSOSd7miJxFGo3GrC954a6BUvcWGSlashLAWcqycEKhnRFRanJWGPlusewClyh3WGSlash6OY4ESm25t&id=11329',
 'https://www.tfrin.gov.tw/theme_data.php?id=194&theme=aquatic_technology',
 'https://www.tfrin.gov.tw/theme_data.php?id=505&sub_theme=fishery&theme=qa',
 'https://www.tfrin.gov.tw/theme_data.php?id=89&theme=aquatic_technology',
 'https://www.tfrin.gov.tw/ws.php?id=205',
}
URL_ERRORS={
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=AmBy1bWviljJtutFM67rWGSlashSkT6B0LNQa70L5O2o6Sz3LXimNnQgWGEqualQVMhQjRe2VWGPlusgmZJ3lNb7pCQPAUxWh83oCSB0OUWbXxvCeoQw93DPw4bb3&id=91',
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=KELAWGEqualWGEqualSJmHp3btafT65EIDfP&id=13396',
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=TxJX1jwWGEqualWGEqualxxtcVR93fdEONWGPlusK&id=13365',
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=kAQdNmcnqosGHKer4iYetlbWGPlusEz9bE916GhpAWGEqualWGEqualOeAfIF3oPfMRMgEpFOWGPlusTvaapnepKVGqSF9eYj6lZFWe5lEGzwQ&id=89',
 'https://www.tfrin.gov.tw/redirect_files.php?file_name=xTw2fNUbAIsga5ML7kM5cilWENZeNJEXnefxxJlTGgto02XxqywPAzXKySFjNnou&id=64168',
 'https://www.tfrin.gov.tw/theme_data.php?id=485&sub_theme=fishery&theme=qa',
 'https://www.tfrin.gov.tw/theme_data.php?id=609&sub_theme=fishery&theme=qa',
}
LAW_URL='https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print'
LAW_VERSION='動物用藥品使用準則；官方頁列修正日期民國114-01-08；本輪官方網頁可讀取，非本機HTML原件'
LAW_ART7='前項停藥期應按實足日數計算。二種以上之動物用藥品合併投予動物時，其停藥期以其中最長者為準。'
LAW_ART3='水產動物用藥品之品目、使用對象、用途、用法、用量、停藥期及使用上應注意事項等，應符合附件一水產動物用藥品使用規範規定。'
LAW_ART2='非獸醫師（佐）處方藥品應依中央主管機關核定之產品標籤及仿單中所記載之內容使用。'
PDF_INFO={
 'data/recovery/raw_sources/moa_animal_drug_use_rules_attachment_1_FL035443.pdf':{
  'source_id':'S09','sha256':'b13b9492322d7c0de2e1f7bc4dcee8feb99431ca1085819a697f3966c6b92e3c',
  'version':'動物用藥品使用準則附件一；對應官方頁114-01-08修正版本；14頁PDF',
  'questions':None},
 'my_data/my_data/動物用藥品管理法.pdf':{
  'source_id':'S12','sha256':'f90b9274bdc57bc4c99d1a988872ec3e4783efb6355de9fd7ab4929eace27c67',
  'version':'動物用藥品管理法本機PDF；官方頁列修正日期105-11-09；12頁PDF',
  'questions':None},
 'data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf':{
  'source_id':'S05','sha256':'274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1',
  'version':'水產試驗所金目鱸養殖生物安全手冊；GPN 4711400105；出版日期114-11-30；100 PDF頁',
  'questions':None},
}
PASSAGE_PHRASES={
 'FT-seabass-Q11':'低於23℃食慾下降',
 'FT-seabass-Q13':'供水與排水為同一渠道',
 'FT-seabass-Q17':'快速游動',
 'FT-seabass-Q28':'每日量測溶氧',
 'FT-seabass-Q30':'低於23℃食慾下降',
}

def readjl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def writej(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def writjl(p,rows):
 with p.open('w',encoding='utf-8',newline='\n') as f:
  for r in rows: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def split_urls(value):
 if not isinstance(value,str): return []
 out=[]
 for u in re.split(r'[\r\n]+',value):
  u=u.strip().strip(',; ')
  if u.startswith(('https://','http://')): out.append(u)
 return out
def normalized_match(text,phrase):
 nt=[]; idx=[]
 for i,ch in enumerate(text):
  if ch.isspace(): continue
  nt.append(ch); idx.append(i)
 n=''.join(nt); np=''.join(ch for ch in phrase if not ch.isspace())
 k=n.find(np)
 if k<0: return None
 return text[idx[k]:idx[k+len(np)-1]+1]
def clean_excerpt(text,limit=100):
 s=re.sub(r'\s+',' ',text or '').strip()
 return s[:limit]

rows=readjl(MAP)
docs=readjl(LOCAL_DOCS)
candidates=readjl(LOCAL_CAND)
cmap={r['question_id']:r for r in candidates}
docmap={}
for d in docs:
 p=ROOT/d['path']
 docmap[d['path']]={**d,'exists':p.is_file(),'actual_sha256':sha(p) if p.is_file() else None,'sha256_match':p.is_file() and sha(p)==d['sha256']}
 pdf_texts={}
 for path,info in docmap.items():
  p=ROOT/path
  if p.is_file():
   reader=PdfReader(str(p),strict=False)
   pdf_texts[path]=[page.extract_text() or '' for page in reader.pages]

# Normalize the source registry: the prior Phase-H network probe treated embedded line breaks as one URL.
url_questions={}
for row in rows:
 vals=list(row.get('source_urls') or [])+list(row.get('candidate_source_urls') or [])
 vals += [x.get('URL','') for x in (row.get('source_records') or []) if isinstance(x,dict)]
 for val in vals:
  for u in split_urls(val): url_questions.setdefault(u,set()).add(row['question_id'])
url_rows=[]
for u,ids in sorted(url_questions.items()):
 status='browser_page_readable' if u in URL_READABLE else ('browser_tool_internal_error' if u in URL_ERRORS else 'not_opened')
 url_rows.append({'source_url':u,'question_ids':sorted(ids),'question_count':len(ids),'browser_access_status':status,
  'captured_at':NOW,'capture_method':'Codex official web open; read-only page visibility only',
  'original_http_bytes_saved_locally':False,'source_file_integrity_verified':False,
  'shell_direct_http_probe':'blocked by Windows socket policy: WinError 10013; no proxy change or bypass attempted',
  'version_or_page_content_verified':status=='browser_page_readable',
  'limitation':'A readable page is not proof of downloadable local original bytes, full-page archival, license for indexing, or current document version.'})
writjl(OUT/'source_url_accessibility_30.jsonl',url_rows)
writej(OUT/'source_url_accessibility_summary.json',{
 'source_mapping_question_records':len(rows),'normalized_unique_actual_urls':len(url_rows),
 'browser_page_readable_urls':sum(x['browser_access_status']=='browser_page_readable' for x in url_rows),
 'browser_internal_error_urls':sum(x['browser_access_status']=='browser_tool_internal_error' for x in url_rows),
 'not_opened_urls':sum(x['browser_access_status']=='not_opened' for x in url_rows),
 'question_records_without_local_source_original':151,'question_records_with_local_source_original':29,
 'local_originals_question_count_basis':'union of the 3 phase-H source-document mappings, excluding the erroneous FT-milkfish-Q12 association to the Animal Drug Administration Act',
 'local_original_source_file_count':3,'local_original_checksums_match':all(d['sha256_match'] for d in docmap.values()),
 'local_original_bytes_downloaded_this_phase':0,'direct_shell_http_errors':'WinError 10013 on authorized normal socket route; no bypass attempted',
 'important':'URL visibility and source content availability are distinct. 151 remaining question records have source URL metadata but no local verified original.'})

def local_pdf_for_q(qid):
 if qid=='FT-milkfish-Q12': return None
 if qid=='FT-seabass-Q28':
  return 'data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf'
 for path,info in docmap.items():
  if qid in (info.get('questions') or []): return path
 return None
def first_matching_pdf_quote(qid,path):
 phrase=PASSAGE_PHRASES.get(qid)
 if not phrase or path not in pdf_texts: return None
 cand=cmap.get(qid,{})
 pages=cand.get('candidate_pages') or []
 order=[x.get('page') for x in pages if isinstance(x,dict) and isinstance(x.get('page'),int)]
 for page_no in order:
  if page_no<1 or page_no>len(pdf_texts[path]): continue
  text=pdf_texts[path][page_no-1]
  quote=normalized_match(text,phrase)
  if quote: return {'pdf_page':page_no,'quote':quote,'page_text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
 for page_no,text in enumerate(pdf_texts[path],1):
  quote=normalized_match(text,phrase)
  if quote: return {'pdf_page':page_no,'quote':quote,'page_text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
 return None

access_by_url={x['source_url']:x for x in url_rows}
source_records=[]; local_quote_rows=[]
for r in rows:
 qid=r['question_id']; local_path=local_pdf_for_q(qid); qid_pages=cmap.get(qid,{}).get('candidate_pages') or []
 urls=[]
 for val in list(r.get('source_urls') or [])+list(r.get('candidate_source_urls') or [])+[x.get('URL','') for x in (r.get('source_records') or []) if isinstance(x,dict)]:
  urls.extend(split_urls(val))
 urls=list(dict.fromkeys(urls))
 accessible=[u for u in urls if access_by_url.get(u,{}).get('browser_access_status')=='browser_page_readable']
 base={'question_id':qid,'species':r.get('species'),'question_text':r.get('question_text'),
  'candidate_reference_answer':r.get('candidate_reference_answer'),'source_id':(r.get('source_ids') or [None])[0],
  'source_urls':urls,'source_url_browser_status':'browser_page_readable' if accessible else ('browser_tool_internal_error' if urls and all(access_by_url.get(u,{}).get('browser_access_status')=='browser_tool_internal_error' for u in urls) else ('URL_not_opened' if urls else 'source_URL_missing')),
  'local_original_path':local_path,'local_original_sha256':docmap.get(local_path,{}).get('actual_sha256') if local_path else None,
  'local_original_checksum_verified':docmap.get(local_path,{}).get('sha256_match',False) if local_path else False,
  'source_version':docmap.get(local_path,{}).get('version') if local_path else next((x.get('文件／頁面') for x in r.get('source_records',[]) if x.get('文件／頁面')),None),
  'quote_capture_method':None,'exact_quote':None,'page_or_locator':None,'quote_verified':False,
  'answer_supported':None,'species_applicability':'not_independently_verified','blocker_reason':None,
  'human_gold_reviewed':False,'evaluation_level':'AI-assisted source trace; NOT_HUMAN_GOLD'}
 if qid.endswith('-Q18'):
  base.update({'source_id':'S09','source_version':LAW_VERSION,'quote_capture_method':'official_law_webpage_read_only; lines 47-49',
   'exact_quote':LAW_ART3,'page_or_locator':'動物用藥品使用準則第3條；Codex official web retrieval lines 47-49 (not archived as raw HTML)',
   'quote_verified':True,'answer_supported':'partial',
   'species_applicability':'general aquatic-animal drug rule; not species-specific',
   'blocker_reason':'條文指定應符合附件一，但未直接規定題庫所述「舊文章僅作背景」及記錄查核日期，需將其作為版本管理政策另核。'})
 elif qid.endswith('-Q27'):
  base.update({'source_id':'S09','source_version':LAW_VERSION,'quote_capture_method':'official_law_webpage_read_only; Article 7 lines 63-66',
   'exact_quote':'前項停藥期應按實足日數計算。','page_or_locator':'動物用藥品使用準則第7條第2項；官方頁 lines 63-66',
   'quote_verified':True,'answer_supported':True,'species_applicability':'generic legal calculation; hypothetical product assumption supplied by question',
   'blocker_reason':'日期計算可依題目明示的7日實足日假設驗證，最早日期為2026-01-18；不得將假設延伸為任何實際產品的停藥期。'})
 elif qid.endswith('-Q29'):
  base.update({'source_id':'S09','source_version':LAW_VERSION,'quote_capture_method':'official_law_webpage_read_only; Article 7 lines 65-66',
   'exact_quote':'二種以上之動物用藥品合併投予動物時，其停藥期以其中最長者為準。','page_or_locator':'動物用藥品使用準則第7條第2項；官方頁 lines 65-66',
   'quote_verified':True,'answer_supported':True,'species_applicability':'general aquatic-animal legal rule; legality of combination is a question premise',
   'blocker_reason':'12日答案由現行第7條的最長停藥期規則直接支持；題目已假設合併使用合法，不代表任何指定產品可合併使用。'})
 elif qid.endswith('-Q28') and local_path and ('animal_drug' in pathlib.Path(local_path).name.lower() or '動物用藥品' in pathlib.Path(local_path).name):
  base.update({'source_id':'S09','source_version':LAW_VERSION,'quote_capture_method':'official_law_webpage_read_only; Article 2 lines 42-49',
   'exact_quote':LAW_ART2,'page_or_locator':'動物用藥品使用準則第2條；官方頁 lines 42-46',
   'quote_verified':True,'answer_supported':'partial','species_applicability':'general drug-label rule; symptom-specific diagnosis is not established',
   'blocker_reason':'法規只支持依處方／核定標籤用藥，不能單獨證明量測清單、隔離或症狀鑑別等完整答案。'})
 elif qid=='FT-milkfish-Q12':
  base.update({'source_id':'S06','local_original_path':'my_data/my_data/動物用藥品管理法.pdf (erroneous prior association; excluded)',
   'source_version':'actual candidate source is FA-385; not locally archived as source original',
   'quote_capture_method':None,'answer_supported':None,'species_applicability':'虱目魚題目；來源應為漁業署寒害頁',
   'blocker_reason':'前一輪把動物用藥品管理法錯配到寒害問答；不以錯配PDF支持答案。FA-385頁面可讀，但本輪未保存原始HTML。'} )
 elif qid.startswith('FT-seabass-') and qid in PASSAGE_PHRASES:
  hit=first_matching_pdf_quote(qid,local_path) if local_path else None
  if hit:
   support_reason={
    'FT-seabass-Q11':'PDF原文支持金目鱸適溫／低溫食慾及水黴風險的核心部分；其餘管理建議需另證。',
    'FT-seabass-Q13':'PDF原文支持進排水分離及未消毒舊水管理；對病池器具與診斷的延伸未由此引文完全支持。',
    'FT-seabass-Q17':'PDF原文支持VNN症狀，但單此症狀段不足以建立完整診斷流程；另一章需另定位診斷依據。',
    'FT-seabass-Q28':'PDF原文支持每日測量DO、pH及總氨氮；抗生素處置／診斷建議仍需其他證據。',
    'FT-seabass-Q30':'PDF原文支持低於23℃食慾下降，未支持固定死亡時間或全部風險因果。'}[qid]
   printed={'FT-seabass-Q11':'手冊印刷頁14','FT-seabass-Q13':'手冊印刷頁15','FT-seabass-Q17':'手冊印刷頁64','FT-seabass-Q28':'手冊印刷頁14/18/21/23摘要頁','FT-seabass-Q30':'手冊印刷頁14'}[qid]
   base.update({'source_id':'S05','source_version':docmap[local_path]['version'],'quote_capture_method':'pypdf exact substring from local original bytes',
    'exact_quote':hit['quote'],'page_or_locator':f"PDF p.{hit['pdf_page']} ({printed}); page_text_sha256={hit['page_text_sha256']}",
    'quote_verified':True,'answer_supported':'partial','species_applicability':'direct species scope: 金目鱸; retained as 金目鱸, not generalized to 七星鱸',
    'blocker_reason':support_reason})
  else:
   base.update({'source_id':'S05','answer_supported':None,'species_applicability':'金目鱸-specific source; exact span not located',
    'blocker_reason':'Local PDF exists, but a precise quote could not be mapped to the candidate page; no answer-support claim made.'})
 else:
  if local_path:
   base.update({'blocker_reason':'Local original checksum verified, but no question-specific exact support span was independently established in this audit.'})
  else:
   base.update({'blocker_reason':'No local verified original; browser URL readability does not supply a saved, version-pinned source span or establish answer support.'})
 source_records.append(base)
 if local_path or qid=='FT-milkfish-Q12':
  local_quote_rows.append({'question_id':qid,'source_id':base.get('source_id'),'source_path':local_path,
   'source_sha256':base.get('local_original_sha256'),'checksum_verified':base.get('local_original_checksum_verified'),
   'exact_quote':base.get('exact_quote'),'locator':base.get('page_or_locator'),'quote_verified':base.get('quote_verified'),
   'quote_capture_method':base.get('quote_capture_method'),
   'answer_supported':base.get('answer_supported'),'species_applicability':base.get('species_applicability'),
   'blocker_reason':base.get('blocker_reason')})

writjl(OUT/'source_mapping_recovery_180.jsonl',source_records)
writjl(OUT/'local_source_quote_verification.jsonl',local_quote_rows)

phase_h=json.loads((H/'phase_g_root_cause_analysis.json').read_text(encoding='utf-8'))
phase_h['phase_i_recheck']={
 'original_reported_labels':{'U':897,'0':3,'precise_p_at_5_n':0},
 'actual_phase_g_valid_round1_contexts':10,'actual_phase_g_valid_round2_contexts':5,
 'phase_g_first_round_missing_slots':890,'phase_g_second_round_missing_slots':895,
 'phase_g_persisted_timeout_or_api_errors':0,
 'actual_phase_g_error':'three batch failures: returned ordinal IDs and malformed/duplicate JSON; pipeline stopped early; finalizer represented absent passes as U',
 'phase_h_integrity_reconfirmed':'All 900 full contexts and SHA256 values existed in original retrieval trace; no missing chunk text caused the 895 missing rounds.',
 'phase_i_attempt_1':'Initial compact constrained response hit num_predict truncation (1100 tokens); raw response saved to pilot_annotation_errors.jsonl; overlapping Python request processes were later found and stopped.',
 'phase_i_attempt_2':'One-question-per-call constrained response parsed, but exact quote validation rejected a quote borrowed from a different passage; this was correctly rejected and preserved in pilot_v2_annotation_errors.jsonl.',
 'phase_i_repair':'Ranks are omitted from Judge output and bound by program position; output shortened and streamed; strict exact-quote verification remains fail-closed; retries capped at 2; raw replies/checkpoints persisted; pass 2 receives no pass 1 result.'}
writej(OUT/'phase_g_root_cause_analysis.json',phase_h)

print(json.dumps({'questions':len(rows),'unique_actual_urls':len(url_rows),'browser_readable_urls':sum(x['browser_access_status']=='browser_page_readable' for x in url_rows),
 'browser_internal_error_urls':sum(x['browser_access_status']=='browser_tool_internal_error' for x in url_rows),
 'local_source_mapped_questions':len(set(d for doc in docs for d in doc.get('questions',[]) if d!='FT-milkfish-Q12')),
 'source_rows':len(source_records),'local_quote_rows':len(local_quote_rows),'local_pdf_checksums_match':all(d['sha256_match'] for d in docmap.values())},ensure_ascii=False))
