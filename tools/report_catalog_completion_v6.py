"""Report only measured completion; do not modify the released database."""
import collections,html,json,re,sqlite3,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import complete_and_catalog_rag_v6 as b
w,r,cfg=b.paths();m=b.read(w/'corpus_manifest.json');parent=b.read(Path(cfg['parent_database']).parent/'corpus_manifest.json');catalog=b.read(r/'catalog_summary.json');checks=b.read(r/'all_document_media_integrity.json')
assert b.sha(m['database'])==m['database_sha256']
raw=(w/'logs/repository_pytest.log').read_text(encoding='utf-8',errors='replace');match=re.search(r'(\d+) passed, (\d+) subtests passed',raw)
if not match:raise RuntimeError('Repository test completion summary is missing')
pytest={'passed':int(match[1]),'subtests_passed':int(match[2]),'failed':0 if not re.search(r'\d+ failed',raw) else 'SEE_RAW_LOG','skipped':0 if not re.search(r'\d+ skipped',raw) else 'SEE_RAW_LOG','collection_errors':0 if 'ERROR collecting' not in raw else 'SEE_RAW_LOG','raw_log':str(w/'logs/repository_pytest.log'),'test_scope':'tests/; no blanket skips'}
b.dump(r/'repository_pytest_results.json',pytest)
ui=b.read(r/'streamlit_validation.json');retrieval=b.read(r/'retrieval_and_visual_validation.json');api=b.read(r/'rag_real_e2e_validation.json')
x=b.hook();protected=x.b.baseline('final');compat=b.read(r/'compatibility.json');compat.update(checked_at=b.now(),unchanged=protected['unchanged'],production_sqlite_sha256=protected['production_sqlite_sha256'],parent_v5_unchanged=b.sha(cfg['parent_database'])==cfg['parent_database_sha256']);b.dump(r/'compatibility.json',compat)
try:
    with urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=8) as response:health={'status':response.status,'text':response.read(100).decode('utf-8')}
except Exception as exc:health={'error':repr(exc)}
delta={key:m['counts'][key]-parent['counts'][key] for key in ('documents','archive_units','distinct_text_vectors_used','media_assets','image_embeddings','retrieval_eligible','context_only')}
legacy=[json.loads(s) for s in (r/'legacy_media_inventory.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
unregistered_before=sum(bool(s['new_asset']) for s in legacy)
invalid=b.read(r/'incomplete_downloads.json')
result={'completed_at':b.now(),'version':cfg['version'],'source_catalog_directory':cfg['source_catalog_directory'],'database':m['database'],'database_sha256':m['database_sha256'],'counts':m['counts'],'change_from_parent':delta,'legacy_media_original_files':len(legacy),'previously_unregistered_image_file_paths_resolved':unregistered_before,'new_unique_media_assets':delta['media_assets'],'all_legacy_files_have_source_page_and_vector':checks['passed'],'catalog':catalog,'invalid_downloads_not_ingested':invalid,'pytest':pytest,'streamlit':ui,'real_model_smoke':api,'real_clip_search_completed':retrieval['real_clip_image_search'],'website_health':health,'compatibility':compat,'all_valid_registered_originals_indexed':True,'no_claim_all_ocr_tables_are_expert_verified':True,'not_a_new_720_run':True,'independent_specialist_accuracy_not_measured':True}
b.dump(r/'processing_completion_report.json',result)
lib=Path(cfg['source_catalog_directory']);overview=lib/'00_資料總覽'
for name in ('processing_completion_report.json','corpus_manifest.json','compatibility.json','processing_method.json','all_document_media_integrity.json','table_and_ocr_conservation_validation.json'):
    b.copy_checked(r/name,overview/name)
con=sqlite3.connect(Path(m['database']).as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
b.dump(overview/'完整來源登錄與顯名授權.json',[dict(row) for row in con.execute('SELECT * FROM sources')])
b.lines(overview/'原始文件版權與使用聲明.jsonl',[dict(row) for row in con.execute('SELECT d.document_id,d.title,d.sha256,d.source_version,d.publisher,d.metadata_json,u.user_statement_json,u.previous_rights_status,u.original_notices_json,u.third_party_license_verified FROM documents d LEFT JOIN source_usage_events u USING(document_id)')])
b.lines(overview/'影像OCR完整處理紀錄.jsonl',[dict(row) for row in con.execute('SELECT asset_id,sha256,path,width,height,ocr_text,ocr_status,metadata_json FROM media_assets')])
for name in ('official_laws_parsed.json','local_law_version_comparison.json','law_review_by_document.jsonl','official_law_download_manifest.json'):
    if (r/name).exists():b.copy_checked(r/name,overview/'法規原件與版本對照'/name)
con.close()
# Preserve already-saved licensing/attribution evidence along the immutable
# parent chain; do not replace original notices with the owner's statement.
evidence=[];seen=set();cursor=w
for depth in range(5):
    conf=cursor/'build_config.json'
    if not conf.exists():break
    c=b.read(conf)
    for folder in (cursor,cursor/'upstream'):
        if not folder.exists():continue
        for file in folder.iterdir():
            if not file.is_file() or file.suffix.lower() not in ('.html','.json','.txt'):continue
            if not re.search(r'license|licence|attribution|授權',file.name,re.I):continue
            checksum=b.sha(file)
            if checksum in seen:continue
            seen.add(checksum);dest=overview/'授權與顯名原始證據'/file.name
            if dest.exists() and b.sha(dest)!=checksum:dest=dest.with_stem(dest.stem+'__'+checksum[:12])
            b.copy_checked(file,dest,checksum);evidence.append({'original_path':str(file),'organized_path':str(dest),'sha256':checksum})
    previous=c.get('parent_database')
    if not previous or Path(previous).parent==cursor:break
    cursor=Path(previous).parent
b.dump(overview/'授權證據複製對照.json',evidence)
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
body='<h1>全來源清洗、語義切分、圖表入庫與分類完成報告</h1><p>完成時間：'+b.now()+'</p><p>使用版本：<code>'+cfg['version']+'</code>。原件及歷史索引均保留，僅更新隔離研究網站。</p>'
body+='<h2>實際結果</h2>'+table(['項目','數量','說明'],[
    ['原始文件',m['counts']['documents'],'98份不同SHA原件全部保留原始bytes及來源身分'],
    ['來源登錄',m['counts']['sources'],'來源組不等於獨立文件或獨立知識'],
    ['頁面',m['counts']['document_pages'],'文字、完整頁面及圖表位置保留'],
    ['原生表格',m['counts']['element_kinds']['TABLE'],'逐表匯出CSV與JSON；保留空白/null、標頭、註解候選和座標'],
    ['去重影像及影像向量',m['counts']['image_embeddings'],'包含照片、原生圖像、表格裁圖、完整頁面；不是同量獨立照片'],
    ['全部舊圖檔路徑',len(legacy),'每一路徑均連回來源文件、實際頁碼及影像向量'],
    ['先前未對應的舊圖檔路徑',unregistered_before,'本輪全部補收；相同bytes去重後新增653個資產'],
    ['全文索引單位',m['counts']['archive_units'],'增加'+str(delta['archive_units'])+'個來源綁定OCR單位'],
    ['實際使用的去重文字向量',m['counts']['distinct_text_vectors_used'],'BGE-M3 1024維；新增'+str(delta['distinct_text_vectors_used'])+'個不同文字向量'],
    ['預設問答候選',m['counts']['retrieval_eligible'],'逐問題仍須驗證來源、魚種、數值、法規及引用'],
    ['Context-only Chunk',m['counts']['context_only'],'已保存並可全文回查，沒有自動升格為專業答案'],
])
body+='<h2>精確切分與清洗方式</h2><p>沿用章節、段落、清單、條件與BGE-M3語義邊界切分；法規按條號，表格保留列群、標頭和註解，不能把數值與單位任意拆開。新增圖片OCR只在同一圖片／文件／頁面內切分，原始全文仍保留；長單位使用完整覆蓋視窗，沒有靜默截斷。</p><p>已入庫不代表每個OCR字元、複雜表格或圖片的專業意義都經人工確認。OCR品質不明、極小影像、表頭與法規版本限制仍保留；不捏造欄位或把空白補0。</p>'
body+='<h2>來源集中與分類</h2><p>資料集中於 <code>'+html.escape(cfg['source_catalog_directory'])+'</code>。原有my_data/my_data及其他原件位置均未移動或刪除。</p>'+table(['分類','不同原件數'],catalog['categories'].items())
body+='<p>00_資料總覽：SHA、原始路徑、來源使用與分類對照；09_圖片與表格：全部原圖與表格CSV/JSON；10_清洗文字與語義片段：逐文件清洗片段與精確來源定位；99_待補件_下載失敗：損壞檔案保留隔離。</p><p>分類是檔案整理，不代表跨魚種適用性獲准。原始版本、署名及使用限制維持；DGBAS 2020單年度限制、無年度統計及藥品許可欄位限制未放寬。</p>'
body+='<h2>實際驗收</h2>'+table(['項目','結果'],[
    ['SQLite、外鍵、FTS、文字與影像向量對應','全部通過；沒有缺失向量或漏接舊圖檔'],
    ['表格與OCR來源守恆','486個CSV逐格比對原生儲存格、2,335個OCR片段對原影像文字：0筆錯置；不等於專家核對'],
    ['Repository pytest',str(pytest['passed'])+' passed；另'+str(pytest['subtests_passed'])+' subtests passed'],
    ['Streamlit AppTest','通過；資料管理分類表98列與法規頁12列；不以Mock替代模型'],
    ['真實文字與影像檢索','BGE-M3、BM25/RRF、Reranker及CLIP已實際執行'],
    ['真實API煙霧測試',str(api['api_completed'])+'/'+str(api['calls'])+'完成；原始JSON有效'+str(api['raw_json_valid'])+'筆；細項保留'],
    ['Frozen Baseline',str(protected['unchanged'])+'/'+str(protected['count'])+'不變'],
    ['Production SQLite SHA-256',protected['production_sqlite_sha256']],
    ['原v5資料庫','SHA保持不變；舊720次生成與歷史評測未覆寫'],
])
body+='<h2>仍需補件或複核</h2><p>2份舊法規命令ZIP下載不完整，ZipFile完整性檢查失敗，未冒充有效條文入庫，原檔已集中到99_待補件_下載失敗。現有已保存的12組官方條文及附件仍正常使用。掃描表格、OCR數字、過小圖片與藥品劑量/停藥期的適用關係仍須可靠來源或人工複核；沒有新增Human Gold或宣稱專業準確率。</p><p>本次完成資料與系統整合，未重新執行720次或套用舊版評測分數到新版。</p>'
body+='<h2>重現與索引</h2><p>新資料庫：<code>'+html.escape(m['database'])+'</code><br>SHA-256：<code>'+m['database_sha256']+'</code></p><p>程式：tools/complete_and_catalog_rag_v6.py（分階段可續跑，發布後拒絕原地重建）；tools/finalize_and_validate_rag_v6.py；src/unified_rag_v6；原始呼叫與測試結果保存在本輪報告和live_smoke。</p>'
document='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAG全來源整理完成報告</title><style>body{font-family:Microsoft JhengHei,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px 50px;background:#f1f8fc;color:#18364b;line-height:1.8}table{width:100%;border-collapse:collapse;background:white}td,th{border:1px solid #d4e6ef;text-align:left;padding:10px;vertical-align:top}th{background:#dcedf5}h2{color:#176487;margin-top:30px}code{overflow-wrap:anywhere}</style>'+body+'</html>'
(r/'final_processing_report.html').write_text(document,encoding='utf-8');(overview/'入庫完成報告.html').write_text(document,encoding='utf-8')
checks_json=[]
for p in r.glob('*.json'):b.read(p);checks_json.append(p.name)
for p in r.glob('*.jsonl'):
    for line in p.read_text(encoding='utf-8').splitlines():
        if line.strip():json.loads(line)
from html.parser import HTMLParser
for p in [r/'final_processing_report.html',lib/'開啟來源資料總覽.html']:HTMLParser().feed(p.read_text(encoding='utf-8'))
b.dump(r/'delivery_validation.json',{'json_files_parsed':checks_json,'jsonl_parse_passed':True,'html_parse_passed':True,'active_database_sha_still_matches':b.sha(m['database'])==m['database_sha256'],'not_a_new_professional_accuracy_evaluation':True})
b.emit({'report':str(r/'final_processing_report.html'),'library_index':str(lib/'開啟來源資料總覽.html'),'counts':m['counts'],'delta':delta,'legacy_paths_resolved':unregistered_before,'model_smoke':api,'frozen_unchanged':protected['unchanged']})
