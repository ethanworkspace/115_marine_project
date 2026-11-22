import json, hashlib, re
from pathlib import Path
from collections import Counter
import pymupdf

ROOT=Path.cwd()
X=ROOT/'reports/evaluation/fish_test_phase_x_20261019_162147'
W=ROOT/'reports/evaluation/fish_test_phase_w_20261019_133804'
V=ROOT/'reports/evaluation/fish_test_phase_v_20261018_224918'
def jl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def j(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def dumpj(name,obj): (X/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def dumpl(name,rows): (X/name).write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def txtsha(s): return hashlib.sha256(s.encode()).hexdigest()

refs=[r for r in jl(W/'reference_answers_v3.jsonl') if r.get('verification_status')=='AI_ASSISTED_CANDIDATE_REQUIRES_RUBRIC_REVIEW']
retr={r['question_id']:r for r in jl(W/'retrieval_results_v3_updated.jsonl')}
profiles={r['question_id']:r for r in jl(W/'question_requirement_profiles_180.jsonl')}
sources={r['source_id']:r for r in jl(V/'source_registry_v3_limited.jsonl')}
direct={
 'FT-tilapia-Q10':'低於15°C時採緊急措施，例如加溫；14.8°C低於此門檻。',
 'FT-mullet-Q01':'烏魚1齡約10,000–20,000尾/公頃。',
 'FT-mullet-Q02':'烏魚2齡以上約5,000–6,000尾/公頃。',
 'FT-mullet-Q11':'2齡以上建議5,000–6,000尾/公頃；12,000尾/公頃高於該章所列範圍，應核對魚齡、面積與現場條件。',
 'FT-mullet-Q19':'3公頃 × 10,000尾/公頃 = 30,000尾.',
 'FT-mullet-Q20':'3公頃 × 20,000尾/公頃 = 60,000尾.',
 'FT-mullet-Q21':'3公頃 × 5,000尾/公頃 = 15,000尾.',
 'FT-mullet-Q22':'3公頃 × 6,000尾/公頃 = 18,000尾.',
 'FT-grouper-Q01':'依該手冊定義的石斑魚組別，27°C落在25–30°C最適成長及存活溫度範圍內。',
 'FT-milkfish-Q01':'14.8°C低於15°C；原文建議低於15°C採緊急措施，例如加溫。',
 'FT-milkfish-Q04':'越冬溝內虱目魚建議密度每立方公尺1.3公斤以下。',
 'FT-seabass-Q01':'30°C位於金目鱸最佳成長溫度28–32°C內。',
 'FT-seabass-Q02':'低於23°C時食慾降低；手冊提醒易因水黴病造成疾病二次感染。',
 'FT-seabass-Q03':'4 psu低於手冊所建議較佳的5 psu以上。',
 'FT-seabass-Q08':'魚苗放養40,000–80,000尾/公頃，體長約6公分以上.'
}
diag={
 'FT-mullet-Q14':('27°C位於題幹提供的26–28°C觀測區間內。','(26+28)/2=27; 題幹比較，不把檢索卡當成台南調查來源。','(26+28)/2','°C'),
 'FT-mullet-Q24':('26–28°C中點為27°C。','midpoint=(lower+upper)/2; 題幹數值。','(26+28)/2','°C'),
 'FT-grouper-Q19':('25–29°C區間寬度為4°C。','width=upper−lower; 題幹數值。','29-25','°C'),
 'FT-grouper-Q22':('是；若範圍包含端點，29°C為25–29°C的上界。','25≤29≤29; 題幹內區間判斷。','25 <= 29 <= 29','boolean'),
 'FT-grouper-Q24':('31°C比題幹29°C上界高2°C。','difference=31−29; 題幹數值。','31-29','°C'),
 'FT-milkfish-Q26':('16.6−15.6=1.0°C。','difference=16.6-15.6; 題幹數值。','16.6-15.6','°C')
}
unavailable={
 'FT-mullet-Q06':'段落只提供生存/最適成長水溫，不是天然海域產卵水溫。',
 'FT-mullet-Q07':'段落沒有描述天然海域產卵環境特徵。',
 'FT-mullet-Q09':'段落沒有題目要求的台南池調查平均水溫與溶氧範圍。',
 'FT-grouper-Q06':'溫度範圍未說明題目要求的具體生理反應。',
 'FT-grouper-Q11':'段落沒有溶氧證據，不能解釋魚群聚集增氧處或提出處置。',
 'FT-milkfish-Q17':'密度上限不足以支持集中於越冬溝的好處與風險兩部分。',
 'FT-seabass-Q30':'段落提供食慾門檻/疾病風險，沒有「一定死亡」或死亡時間。'
}
def quote_for(qid,text):
 rules={
  'FT-tilapia-Q10':('水溫若低於15℃時','俾減輕死亡。'),
  'FT-milkfish-Q01':('水溫若低於15℃時','俾減輕死亡。'),
  'FT-milkfish-Q04':('密度以虱目魚','為宜。'),
  'FT-mullet-Q01':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q02':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q11':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q19':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q20':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q21':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-mullet-Q22':('烏魚1 齡養殖放養密度','現地狀況為準。'),
  'FT-grouper-Q01':('生存溫度','存活溫度。'),
  'FT-seabass-Q01':('最佳成長溫度','5 psu 以上較佳。'),
  'FT-seabass-Q02':('最佳成長溫度','5 psu 以上較佳。'),
  'FT-seabass-Q03':('最佳成長溫度','5 psu 以上較佳。'),
  'FT-seabass-Q08':('建議魚苗放養','以利養殖管理')
 }
 if qid in rules:
  a,b=rules[qid]; i=text.find(a); k=text.find(b,i+len(a)) if i>=0 else -1
  if i>=0 and k>=0: return text[i:k+len(b)],i,k+len(b),True
 needles=['生存之水溫範圍','生存溫度','密度以虱目魚','低於15℃','魚苗放養','放養密度']
 for needle in needles:
  i=text.find(needle)
  if i>=0: return text[max(0,i-25):min(len(text),i+115)],max(0,i-25),min(len(text),i+115),True
 return None,None,None,False

rows=[]
for r in refs:
 qid=r['question_id']; rr=retr[qid]; prof=profiles[qid]; cs=rr.get('reranked_top5',[]); c=cs[0] if cs else {}
 sid=c.get('source_id'); s=sources.get(sid); path=ROOT/Path(s['local_file']) if s else None
 page_m=re.search(r'physical page\s+(\d+)',c.get('page_or_locator') or '')
 page=int(page_m.group(1)) if page_m else None
 exists=bool(path and path.exists()); actual=sha(path) if exists else None; match=bool(s and actual==s.get('sha256'))
 doc=pymupdf.open(path) if exists else None
 page_text=doc[page-1].get_text() if doc and page and page<=len(doc) else ''
 quote,qstart,qend,qok=quote_for(qid,page_text) if page_text else (None,None,None,False)
 status='SOURCE_VERIFIED_AUTOMATED' if qid in direct else ('ARITHMETIC_DIAGNOSTIC_ONLY' if qid in diag else 'NOT_EVALUABLE')
 if status=='SOURCE_VERIFIED_AUTOMATED':
  answer=direct[qid]
  formula=None; tol=None
  if qid in {'FT-mullet-Q19','FT-mullet-Q20','FT-mullet-Q21','FT-mullet-Q22'}:
   density={'FT-mullet-Q19':10000,'FT-mullet-Q20':20000,'FT-mullet-Q21':5000,'FT-mullet-Q22':6000}[qid]
   total=3*density; answer=f'3公頃 × {density:,}尾/公頃 = {total:,}尾。'
   formula='total_fish = pond_area_ha × stocking_density_fish_per_ha'; tol='0 fish, exact integer arithmetic'
  support_ok=match and qok
  if not support_ok: status='SOURCE_VERSION_UNVERIFIED'
  supported=status=='SOURCE_VERIFIED_AUTOMATED'
  rub={'rubric_id':'PX-REF-'+qid,'version':'phase_x_reference_candidate_v1','status':'AI_ASSISTED_NOT_HUMAN_GOLD','criteria':['包含來源支持的必要答案元素與數值','保留物種、單位及原文明示適用條件','不加入未支持的病因、死亡、療效或許可推論']+(['計算及量綱正確'] if formula else []),'pass_rule':'all applicable elements present and no unsupported claim','human_gold_reviewed':False}
  limitation={
   'FT-mullet-Q19':'只適用題目所述烏魚1齡密度；現場條件仍可能調整。',
   'FT-mullet-Q20':'只適用題目所述烏魚1齡密度；現場條件仍可能調整。',
   'FT-mullet-Q21':'只適用題目所述烏魚2齡以上密度；現場條件仍可能調整。',
   'FT-mullet-Q22':'只適用題目所述烏魚2齡以上密度；現場條件仍可能調整。',
   'FT-grouper-Q01':'保留手冊定義的石斑魚組別，不泛化為每個石斑物種。',
   'FT-seabass-Q01':'來源限金目鱸 Lates calcarifer，不泛化為所有鱸魚。',
   'FT-seabass-Q02':'風險提醒不代表必然因果或確診。',
   'FT-seabass-Q03':'僅為金目鱸手冊鹽度建議，不是所有鱸魚門檻。',
   'FT-seabass-Q08':'來源指金目鱸魚苗；原文另要求苗體長約6公分以上。'
  }.get(qid,'來源卡只作有限事實引用，沒有主張全文授權。')
 elif status=='ARITHMETIC_DIAGNOSTIC_ONLY':
  answer,limitation,formula,unit=diag[qid]; tol='0 exact'
  support_ok=False; supported=False
  rub={'rubric_id':'PX-DIAG-'+qid,'version':'phase_x_arithmetic_diagnostic_v1','status':'QUESTION_ONLY_DIAGNOSTIC','criteria':['按題幹數值計算','數值與單位正確'],'pass_rule':'deterministic arithmetic only; excluded from source-verified professional accuracy','human_gold_reviewed':False}
 else:
  answer=None; formula=None; tol=None; limitation=unavailable[qid]; support_ok=False; supported=False
  rub={'rubric_id':'PX-NE-'+qid,'version':'phase_x_reference_candidate_v1','status':'NOT_CREATED_INSUFFICIENT_TOP5_EVIDENCE','criteria':[],'pass_rule':None,'human_gold_reviewed':False}
 expected_abstention=(qid=='FT-seabass-Q30')
 if doc: doc.close()
 rows.append({
  'question_id':qid,'species':r.get('species'),'category':r.get('category'),'original_question':r.get('original_question'),
  'required_answer_elements':prof.get('required_answer_elements'),'required_conditions':prof.get('required_conditions'),
  'source_id':sid,'source_title':c.get('source_title'),'publisher':s.get('publisher') if s else None,'official_url':s.get('source_url') if s else None,
  'source_file':s.get('local_file') if s else None,'source_version':c.get('source_version') or (s.get('version') if s else None),
  'source_sha256_expected':s.get('sha256') if s else None,'source_sha256_actual':actual,'source_sha256_match':match,
  'corpus_version':rr.get('corpus_version'),'context_count':len(cs),'top5_chunk_id':c.get('chunk_id'),'top5_rank':c.get('rank'),
  'chunk_sha256':c.get('content_sha256'),'chunk_text':c.get('content'),'exact_source_locator':c.get('page_or_locator'),
  'exact_source_text_span':quote,'source_span_start_char':qstart,'source_span_end_char':qend,'source_span_in_extracted_pdf':qok,
  'source_page_text_sha256':txtsha(page_text) if page_text else None,
  'source_usage_basis':s.get('usage_scope') if s else None,'rights_assessment':s.get('rights_assessment') if s else None,
  'full_text_license_or_index_permission_claimed':False,'usage_limit':'Existing registry limits to narrow factual cards; this record makes no third-party full-text authorization claim.',
  'expected_answer_candidate':answer,'answer_supported':supported,'logical_rubric':rub,'arithmetic_formula':formula,'tolerance':tol,
  'verification_status':status,'support_determination':('Original PDF checksum, exact page span, fact card, species and required values cross-checked by script.' if supported else ('Question-only deterministic diagnostic; retrieved evidence is not its support.' if status=='ARITHMETIC_DIAGNOSTIC_ONLY' else limitation)),
  'limitations':limitation,'expected_abstention':expected_abstention,'human_gold_reviewed':False,'human_gold_status':'NOT_HUMAN_GOLD',
  'candidate_rubric_status':'AI_ASSISTED_CANDIDATE_NOT_LOCKED' if status!='NOT_EVALUABLE' else 'BLOCKED',
  'next_action':'Independent researcher review before locking rubric or scoring model responses.' if status!='NOT_EVALUABLE' else 'Repair retrieval or obtain a directly supporting source before answer scoring.'
 })
dumpl('verified_reference_answer_candidates.jsonl',rows)

findings=[
 {'source_id':'TFRI-145-EEL-BACTERIAL-DISEASE','title':'臺灣養殖鰻魚常見細菌性疾病','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=145&sub_theme=C&theme=epaper_data','access_date':'2026-10-19','observed':'官方頁面索引摘要涉及養殖鰻魚常見細菌病原/病徵及依獸醫處方用藥。','species_scope':'鰻魚候選；須讀完整頁核實','category':['Disease'],'source_bytes_saved':False,'source_integrity':'source_file_integrity_unverified','version':'not_fixed','usage_basis':'not_verified','admission_status':'not_admitted','indexed':False,'blocker':'未保存原始 bytes/checksum，且未核實全文索引條件。'},
 {'source_id':'TFRI-191-FISH-WATER-QUALITY','title':'漁業問答：水質管理/溶氧','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=191&sub_theme=fishery&theme=qa','access_date':'2026-10-19','observed':'官方頁面摘要有魚蝦養殖一般溶氧說明，不能直接當成六魚種各自安全閾值。','species_scope':'一般水產，不是六魚種專屬門檻','category':['Water Quality'],'source_bytes_saved':False,'source_integrity':'source_file_integrity_unverified','version':'not_fixed','usage_basis':'not_verified','admission_status':'not_admitted','indexed':False,'blocker':'完整頁面、更新日期、物種範圍及全文處理條件未固定。'},
 {'source_id':'TFRI-720-TILAPIA-DO','title':'漁業問答：吳郭魚溶氧','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=720&sub_theme=fishery&theme=qa','access_date':'2026-10-19','observed':'官方頁面摘要明確談及吳郭魚及一般養殖魚溶氧管理。','species_scope':'吳郭魚/一般養殖候選','category':['Water Quality'],'source_bytes_saved':False,'source_integrity':'source_file_integrity_unverified','version':'not_fixed','usage_basis':'not_verified','admission_status':'not_admitted','indexed':False,'blocker':'未封存原頁 bytes/checksum，完整適用條件與全文處理範圍未核實。'},
 {'source_id':'TFRI-912-MULLET-DO','title':'漁業問答：烏魚溶氧','publisher':'農業部水產試驗所','official_url':'https://www.tfrin.gov.tw/theme_data.php?id=912&sub_theme=fishery&theme=qa','access_date':'2026-10-19','observed':'官方頁面摘要提及烏魚正常活動/成長相關溶氧值。','species_scope':'烏魚候選','category':['Water Quality'],'source_bytes_saved':False,'source_integrity':'source_file_integrity_unverified','version':'not_fixed','usage_basis':'not_verified','admission_status':'not_admitted','indexed':False,'blocker':'原始頁面 bytes、版本、數值條件及全文索引處理條件待核實。'},
 {'source_id':'MOA-FL035443-ANIMAL-DRUG-USE-RULES','title':'動物用藥品使用準則','publisher':'農業部','official_url':'https://law.moa.gov.tw/LawContent.aspx?id=FL035443','access_date':'2026-10-19','observed':'法規入口可用來核對使用對象、用法、用量及停藥期的規範框架；不能單靠通則推定特定產品許可或停藥天數。','species_scope':'依法規條文/附件逐項核對','category':['Medication / Law'],'source_bytes_saved':False,'source_integrity':'source_file_integrity_unverified','version':'current article/annex snapshot not saved','usage_basis':'law-text use scope must be tied to fixed text/effective date','admission_status':'not_admitted_in_phase_x','indexed':False,'blocker':'本輪未建立條文及附件版本快照。'}
]
dumpl('source_search_findings.jsonl',findings)
status=Counter(x['verification_status'] for x in rows)
imp=j(X/'source_coverage_improvement.json')
imp.update({'phase_x_28_candidate_status_counts':dict(status),'phase_x_source_answer_candidates':status.get('SOURCE_VERIFIED_AUTOMATED',0),
 'phase_x_source_backed_calculation_candidates':sum(x['verification_status']=='SOURCE_VERIFIED_AUTOMATED' and bool(x['arithmetic_formula']) for x in rows),
 'phase_x_question_only_arithmetic_diagnostics':status.get('ARITHMETIC_DIAGNOSTIC_ONLY',0),'phase_x_not_evaluable':status.get('NOT_EVALUABLE',0),
 'new_professional_source_files_admitted':0,'new_corpus_chunks_added':0,'new_formal_species_coverage':0,
 'source_original_files_checked':len({x['source_file'] for x in rows}),'source_original_checksums_matched':len({x['source_file'] for x in rows if x['source_sha256_match']}),
 'official_page_leads_not_admitted':len(findings),'human_gold':0,
 'species_source_answer_candidates':dict(Counter(x['species'] for x in rows if x['verification_status']=='SOURCE_VERIFIED_AUTOMATED')),
 'note':'The 15 checks concern concise factual cards already in the W corpus and four existing originals. This adds answer/provenance verification; it does not add sources, chunks, rights, or formal admissions.'})
dumpj('source_coverage_improvement.json',imp)
print(json.dumps({'rows':len(rows),'status_counts':dict(status),'source_files':len({x['source_file'] for x in rows}),'checksums_matched':len({x['source_file'] for x in rows if x['source_sha256_match']}),'official_page_leads':len(findings)},ensure_ascii=False,indent=2))
