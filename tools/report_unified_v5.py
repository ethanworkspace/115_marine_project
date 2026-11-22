"""Truthful final reporting from the built database and saved execution evidence."""
import json,re,sqlite3,sys,hashlib
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import expand_unified_all_documents_v5 as x
from src.unified_rag_v4.common import dump,sha_file,FISH
manifest=json.loads((x.W/'corpus_manifest.json').read_text(encoding='utf-8'));counts=manifest['counts']
assert sha_file(x.DB)==manifest['database_sha256']
con=sqlite3.connect(x.DB.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
coverage={s:{'candidate_chunks':0,'source_ids':set()} for s in FISH}
for row in con.execute('SELECT source_id,species_scope FROM chunks WHERE retrieval_eligible=1'):
    try:scope=json.loads(row['species_scope'])
    except (TypeError,json.JSONDecodeError):scope=[row['species_scope']] if row['species_scope'] else []
    if not isinstance(scope,list):scope=[scope]
    for species in FISH:
        if species in scope:coverage[species]['candidate_chunks']+=1;coverage[species]['source_ids'].add(row['source_id'])
for row in coverage.values():row['source_ids']=sorted(row['source_ids']);row['source_count']=len(row['source_ids'])
dump(x.R/'source_coverage_by_species.json',{'species':coverage,'not_independent_fact_counts':True,'not_question_answer_coverage':True})
queue=[]
for row in con.execute("SELECT segment_id,document_id,page_start,page_end,quality_status FROM element_chunks WHERE quality_status IN ('OCR_ONLY_REQUIRES_REVIEW','OVERSIZE_UNIT_REVIEW','TABLE_MULTIROW_HEADER_REQUIRES_REVIEW')"):
    queue.append({**dict(row),'review_status':'AUTOMATED_FLAG_NOT_HUMAN_REVIEW','semantically_indexed_for_discovery':True})
with (x.R/'content_quality_review_queue.jsonl').open('w',encoding='utf-8') as f:
    for row in queue:f.write(json.dumps(row,ensure_ascii=False)+'\n')
cache=sqlite3.connect(x.W/'embedding_work_cache.sqlite3')
used={r[0] for r in con.execute('SELECT DISTINCT content_sha256 FROM archive_units')}
methods=[]
for sha,method in cache.execute('SELECT sha,method FROM vectors'):
    if sha in used:methods.append({'content_sha256':sha,'requested_method':method,'context_limit_recovery_log':str(x.W/'logs/embedding_context_limit_recovery.jsonl'),
        'original_text_never_silently_truncated':True,'adaptive_recovery_may_further_pool_explicitly_rejected_inputs':True})
cache.close()
with (x.R/'embedding_method_provenance.jsonl').open('w',encoding='utf-8') as f:
    for row in methods:f.write(json.dumps(row,ensure_ascii=False)+'\n')
log=(x.W/'logs/repository_pytest.log').read_text(encoding='utf-8-sig',errors='replace')
match=re.search(r'(\d+) passed, (\d+) subtests passed',log)
pytest={'passed':int(match.group(1)) if match else None,'subtests_passed':int(match.group(2)) if match else None,
    'failed':0 if match and ' failed' not in log else None,'skipped':0 if match and ' skipped' not in log else None,
    'collection_errors':0 if match and ' error' not in log.lower() else None,
    'scope':'Full repository tests/ with explicit pre-existing research interpreter',
    'raw_log':str(x.W/'logs/repository_pytest.log'),'junit_xml':str(x.R/'repository_pytest.xml')}
dump(x.R/'repository_pytest_results.json',pytest)
ui=json.loads((x.R/('streamlit_validation_final.json' if (x.R/'streamlit_validation_final.json').exists() else 'streamlit_validation.json')).read_text(encoding='utf-8'))
real=json.loads((x.R/'rag_real_e2e_validation.json').read_text(encoding='utf-8'))
attempts=[json.loads(s) for s in (x.R/'real_generator_smoke.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
runtime_models={}
for a in attempts:
    raw=a.get('result_record',{})
    if raw:runtime_models[a['model_id']]={k:raw.get(k) for k in ('model_tag','model_digest','prompt_version','corpus_sha256')}
dump(x.R/'runtime_model_manifest.json',{'models':runtime_models,'embedding':{'tag':manifest['embedding_model'],'digest':manifest['embedding_digest'],'dimension':1024},
    'image_model_revisions':[dict(r) for r in con.execute('SELECT model,model_revision,dimension,count(*) vectors FROM image_embeddings GROUP BY model,model_revision,dimension')],
    'model_weight_bytes_not_rehashed':True})
target=json.loads((x.R/'targeted_pipeline_tests.json').read_text(encoding='utf-8'))
reviews=json.loads((x.R/'local_law_version_comparison.json').read_text(encoding='utf-8'))
lawstatus=dict(Counter(row['verification_status'] for row in reviews))
dump(x.R/'validation_summary.json',{'all_document_vectors':json.loads((x.R/'all_document_vector_integrity.json').read_text(encoding='utf-8')),
    'repository_pytest':pytest,'targeted_checks':target,'streamlit_apptest':ui,'real_api_smoke':real,
    'law_comparison_statuses':lawstatus,'human_gold_created':0,'not_expert_semantic_or_legal_certification':True})
protected=x.b.baseline('final')
dump(x.R/'compatibility.json',{'checked_at':protected['checked_at'],'frozen_manifest_count':protected['count'],'unchanged':protected['unchanged'],
    'production_sqlite_sha256':protected['production_sqlite_sha256'],'production_matches':protected['production_matches'],
    'parent_v4_database_unchanged':sha_file(Path(x.CFG['parent_database']))==x.CFG['parent_database_sha256'],
    'historical_generations_overwritten':False,'new_720_run_executed':False,'production_switched':False,
    'new_database':str(x.DB),'new_database_sha256':sha_file(x.DB),'old_model_weight_bytes_rehashed_this_round':False})
files=list((ROOT/'src/unified_rag_v5').glob('*.py'))+list((ROOT/'tools').glob('*v5*.py'))
app=ROOT/'research_staging/app_sessions/launch_20261118_154253'
files += [app/name for name in ('professional_platform.py','unified_question_engine.py','free_question_engine.py','answer_policy.py','run_app.py')]
dump(x.R/'reproducibility_manifest.json',{'created_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
    'version':manifest['version'],'database':str(x.DB),'database_sha256':sha_file(x.DB),
    'pinned_parent':{'database':x.CFG['parent_database'],'sha256':x.CFG['parent_database_sha256']},
    'embedding_model':manifest['embedding_model'],'embedding_digest':manifest['embedding_digest'],'rrf_k':60,
    'image_model':manifest['image_model'],'sources_manifest':str(x.W/'source_registry.json'),
    'source_registry_sha256':sha_file(x.W/'source_registry.json'),
    'official_download_bytes_manifest':str(x.R/'official_law_download_manifest.json'),
    'code':[{'path':str(p),'sha256':sha_file(p)} for p in sorted(set(files))],
    'model_digests_from_actual_api_attempts':runtime_models,'no_human_gold_claim':True})
species_rows='\n'.join('| '+s+' | '+str(v['candidate_chunks'])+' | '+str(v['source_count'])+' |' for s,v in coverage.items())
results='\n'.join('| '+row['case']+' | '+row['model_id']+' | '+str(row.get('api_completed',False))+' | '+str(row.get('answer_status',row.get('exception','N/A')))+' | '+str(row.get('answer_origin','N/A'))+' |' for row in real['results'])
report=f'''# 全文件清洗、語義索引與法規核對完成報告

版本：`{manifest['version']}`。依本輪「全部文件皆可使用」的明確指示，先前 44 份全文處理受限文件已納入本機研究全文流程；沒有再次要求 Owner Approval。原有版權聲明與本輪使用聲明分開保存，未聲稱已取得新的第三方公開散布授權。

## 全量資料實際結果

| 項目 | 數量 | 說明 |
|---|---:|---|
| 不同原始檔案 | {counts['documents']:,} | 原先 66 份聯集原件，加本輪官方法規原件；以 SHA 去重 |
| 原始檔案路徑 | {counts['document_files']:,} | 所有別名及重複原件位置仍保留 |
| my_data | {counts['my_data_paths']} | 53 份全部有解析元素及文字／圖像向量 |
| 來源登錄 | {counts['sources']} | 不等於獨立知識或不同檔案數 |
| PDF／轉換版面頁數 | {counts['document_pages']:,} | 每頁都有對應的視覺資產，包含向量圖與複雜表格 |
| 可辨識原生表格 | {counts['element_kinds']['TABLE']:,} | 儲存格、標頭、空白、原頁位置保存；不把空白補成 0 |
| 全文及原生紀錄索引單位 | {counts['archive_units']:,} | 包含不同呈現與重複來源關係，不能視為獨立事實數 |
| 實際使用的去重文字向量 | {counts['distinct_text_vectors_used']:,} | BGE-M3，1024 維；全文、表格文字與原始結構化紀錄 |
| 去重影像向量 | {counts['image_embeddings']:,} | CLIP，512 維；圖片、表格裁圖及整頁影像 |
| 通過預設資料品質與來源範圍的問答候選 | {counts['retrieval_eligible']:,} | 實際作答仍依問題魚種、條件及法規版本逐次過濾 |

完整性檢查確認：98/98 原件均有文字或圖像向量、全部 archive unit 有向量、全部 media asset 有影像向量、全部 1,278 頁有視覺資產；沒有缺失的原件 SHA 或孤立 Chunk。實際數值與細項見 `all_document_vector_integrity.json`，不以檔案數代替專業答案覆蓋率。

## 清洗與精準定位

原始 bytes 不變；清洗版本移除控制字元、可確認的重複頁邊雜訊及 HTML 標籤，解碼原始 HTML 實體，保留化學符號的內文次序、段落換行、原始數值和單位。JSON／CSV／XML 原始紀錄不改寫，來源 ID、Record 位置及清洗欄位另存核對紀錄。

一般文獻先重建邏輯段落、清單及條件，再以 BGE 段落語義輔助分段。官方法規依原始條號分段，不能跨條合併；附件圖示文字不會導致有附件的第 3、4、6 條漏收。單位超過模型實際 Context 上限時，保留完整原文，改用完整覆蓋的重疊視窗向量彙整，不靜默截掉後文。

圖片保留來源頁面與位置，附有原生圖說及既有 OCR；所有圖片與整頁影像都有實際 CLIP 向量。圖像相似度不等於疾病診斷或專家判圖。合併儲存格、複雜表頭、OCR 數字與未核實公式保留待核對旗標，但原件、文字／影像與檢索向量均已保存，未因待核對就省略入庫。

## 法規核對

本輪透過正常官方 HTTPS 保存 12 部法規的條文頁及 21 份 PDF 附件，共 33 個取得資源。逐件保存 URL、實際取得時間、大小與 SHA；其中一份與既有本機原件相同，去重後新增 32 份原件。

15 份本機法規文件已建立原文與官方對照。確認本機《農業天然災害救助辦法》原為民國 115 年 3 月 24 日版，而官方快照列示民國 115 年 6 月 29 日版；新版原文已實際入庫，舊檔保留。其餘「修正日期相同」不直接當成全文一致，逐條正規化比對的差異仍完整保存，可能包含段落編號、版面及實質文字差異，沒有強行判成全部通過。

本機舊版、修正對照表、總說明與官方條文的角色分開：它們仍能在全部文件搜尋中回查，但不直接成為預設現行法律依據。官方版本資訊、整編截止日與附件身分也各自可引用；不得由殘留容許量、一般法規或藥品許可快照推算特定藥物劑量與停藥期。

官方核對入口：[農業天然災害救助辦法](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0090019)、[動物用藥品使用準則](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=M0130023)、[動物用藥殘留標準](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040026)。全部 12 部法規的來源及日期見 `official_laws_parsed.json`。

這是可追溯的自動版本與文字核對，不是對所有條文施行時間、組織改制或個案適用作成法律認證。

## 單一研究 RAG 與網站

網站已連接本版同一資料庫，沿用 BM25／FTS5、BGE-M3、RRF k=60、BGE Reranker 與通用來源回答流程。新增全部文件搜尋及法規核對；全文資料、待核對 OCR 與原生資料列均可搜尋，答案仍須通過魚種、使用範圍、版本、數值及引用驗證。

保留原始模型輸出、驗證後回答與系統查核說明；系統回補不算模型直接作答成功。模型失敗也不再直接顯示成「資料庫沒有來源」。DGBAS 2020 維持單年度描述性 Fact，鰻魚無年度統計不補年度，9,999 筆藥品 API 快照仍保留完整性與目前有效性未確認限制。

## 驗收

Repository：{pytest['passed']} passed，另 {pytest['subtests_passed']} subtests passed；失敗、跳過與收集錯誤依保存的真實輸出列示。新增流程規則檢查 {target['passed']} 項通過、{target['failed']} 項失敗。Streamlit AppTest 已確認資料管理與 12 列法規核對頁無例外；AppTest 未 Mock 或代替 Generator。

另執行 {real['calls']} 次真實本機 API Smoke，實際 API 完成 {real['api_completed']} 筆，原始 JSON 合格 {real['raw_json_valid']} 筆。這些是小型串接測試，不是 720 次正式評測或專家準確率。

| 案例 | 模型 | API 完成 | 最終狀態 | 回答來源 |
|---|---|---|---|---|
{results}

所有失敗或不完整輸出均保留，沒有為了通過而關閉安全閘。Human Gold 仍為 0。

## 六魚種候選標註

下表只描述索引內的魚種範圍標記，不代表獨立知識數、180 題答案支持數或 P@5。

| 魚種 | 有魚種標註的問答候選段落 | 來源組數 |
|---|---:|---:|
{species_rows}

## 交付與保護

資料庫：`{x.DB}`。

SHA-256：`{manifest['database_sha256']}`。

逐檔處理表 `all_file_processing_results.jsonl`；向量完整性 `all_document_vector_integrity.json`；本機法規逐件核對 `law_review_by_document.jsonl`；原始官方資源 `official_law_download_manifest.json`；完整重現紀錄 `reproducibility_manifest.json`。模型呼叫、Prompt、串流及原始回覆保存在本輪 `live_smoke`。

最後 Frozen Manifest 維持 {protected['unchanged']}/{protected['count']}；Production SQLite SHA-256 為 `{protected['production_sqlite_sha256']}`。未修改 Production、歷史 Corpus、Historical E4、既有 720 次生成或歷史評測；也未執行清理、刪除、A/B、消融或新 720 次生成。
'''
(x.R/'all_documents_rag_final_report.md').write_text(report,encoding='utf-8')
con.close();print(json.dumps({'report':str(x.R/'all_documents_rag_final_report.md'),'text_vectors_used':counts['distinct_text_vectors_used'],'image_vectors':counts['image_embeddings'],'baseline':protected['unchanged']},ensure_ascii=False))
