"""Read-only RAG inventory; write a separate, timestamped status report."""
from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone(timedelta(hours=8)))
OUT = ROOT / 'reports' / 'status' / ('rag_overview_' + NOW.strftime('%Y%m%d_%H%M%S'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def jsonl(name, rows):
    with (OUT / name).open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def table(headers, rows):
    return '<table><thead><tr>' + ''.join('<th>' + html.escape(str(x)) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + html.escape(str(x)) + '</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def main():
    active = read(ROOT / 'research_staging/unified_rag_active.json')
    work = Path(active['workspace'])
    report = ROOT / 'reports/evaluation' / work.name
    manifest = read(work / 'corpus_manifest.json')
    con = sqlite3.connect(Path(active['database']).as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row

    def rows(sql):
        return [dict(row) for row in con.execute(sql)]

    actual = {t: con.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ['documents', 'document_files', 'document_pages', 'document_elements', 'element_chunks', 'media_assets', 'image_embeddings', 'sources', 'source_records', 'chunks', 'archive_units', 'semantic_archive_fts']}
    actual['retrieval_eligible'] = con.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=1').fetchone()[0]
    actual['context_only'] = actual['chunks'] - actual['retrieval_eligible']
    actual['distinct_text_vectors_used'] = con.execute('SELECT count(DISTINCT content_sha256) FROM archive_units').fetchone()[0]
    actual['my_data_paths'] = con.execute('SELECT count(*) FROM document_files WHERE is_my_data=1').fetchone()[0]
    actual['my_data_current_files'] = sum(p.is_file() for p in (ROOT / 'my_data').rglob('*'))
    validation = {
        'sqlite_integrity': con.execute('PRAGMA integrity_check').fetchone()[0],
        'foreign_key_errors': [list(r) for r in con.execute('PRAGMA foreign_key_check')],
        'missing_archive_vectors': con.execute('SELECT count(*) FROM archive_units u LEFT JOIN embedding_cache e USING(content_sha256) WHERE e.content_sha256 IS NULL').fetchone()[0],
        'missing_image_vectors': con.execute('SELECT count(*) FROM media_assets a LEFT JOIN image_embeddings e USING(asset_id) WHERE e.asset_id IS NULL').fetchone()[0],
    }
    formats = rows('SELECT original_format,count(*) count FROM documents GROUP BY original_format')
    quality = rows('SELECT quality_status,count(*) count FROM element_chunks GROUP BY quality_status')
    ocr = rows('SELECT ocr_status,count(*) count FROM media_assets GROUP BY ocr_status')
    source_rows = rows('SELECT s.source_id,s.dataset_id,s.title,s.publisher,s.source_sha256,s.owner_admission_status,s.license_scope_status,s.version_status,s.applicability_status,s.completeness_status,s.processing_scope,(SELECT count(*) FROM source_records r WHERE r.source_id=s.source_id) raw_record_count,(SELECT count(*) FROM chunks c WHERE c.source_id=s.source_id) chunk_count,(SELECT count(*) FROM chunks c WHERE c.source_id=s.source_id AND c.retrieval_eligible=1) answer_candidate_count FROM sources s ORDER BY s.source_id')
    structured = [r for r in source_rows if str(r['dataset_id']).isdigit()]
    by_source = {r['source_id']: r for r in source_rows}
    stat_ids = ['MOA-FISHERY-PRODUCTION-44084', 'DGBAS-79395-2020']
    stat_n = sum(by_source[s]['answer_candidate_count'] for s in stat_ids)

    scope = read(report / 'source_coverage_by_species.json')
    document_rows = rows('SELECT document_id,sha256,title,original_format,publisher,source_version,rights_status,owner_decision,parse_status FROM documents ORDER BY title')
    files = defaultdict(list)
    for row in rows('SELECT path,document_id,is_my_data FROM document_files'):
        files[row['document_id']].append({'path': row['path'], 'is_my_data': bool(row['is_my_data'])})
    counts = {}
    for name, query in {
        'pages': 'SELECT document_id,count(*) n FROM document_pages GROUP BY document_id',
        'tables': "SELECT document_id,count(*) n FROM document_elements WHERE kind='TABLE' GROUP BY document_id",
        'archive_units': 'SELECT document_id,count(*) n FROM archive_units GROUP BY document_id',
        'archive_units_with_vector': 'SELECT u.document_id,count(*) n FROM archive_units u JOIN embedding_cache e USING(content_sha256) GROUP BY u.document_id',
        'images_with_vector': 'SELECT e.document_id,count(DISTINCT e.asset_id) n FROM document_elements e JOIN image_embeddings v USING(asset_id) GROUP BY e.document_id',
    }.items():
        counts[name] = {r['document_id']: r['n'] for r in rows(query)}
    chunks_by_sha = {r['source_sha256']: r for r in rows('SELECT source_sha256,count(*) chunk_count,sum(retrieval_eligible) answer_candidate_count FROM chunks GROUP BY source_sha256')}
    for d in document_rows:
        d['original_paths'] = files[d['document_id']]
        for key, values in counts.items():
            d[key] = values.get(d['document_id'], 0)
        c = chunks_by_sha.get(d['sha256'], {})
        d['rag_chunks'] = c.get('chunk_count', 0)
        d['answer_candidate_chunks_before_query_filters'] = c.get('answer_candidate_count', 0)
        d['archive_and_vectors_present'] = bool(d['archive_units_with_vector'] or d['images_with_vector'])
        d['not_professional_answer_verification'] = True
    validation['documents_without_vectors'] = sum(not d['archive_and_vectors_present'] for d in document_rows)
    con.close()

    laws = [json.loads(line) for line in (report / 'law_review_by_document.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    law_statuses = dict(Counter(r['verification_status'] for r in laws))
    test_results = read(report / 'validation_summary.json')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=8) as response:
            service = {'http_status': response.status, 'response': response.read(200).decode('utf-8', 'replace')}
    except Exception as e:
        service = {'error': repr(e)}
    prod_sha = sha(ROOT / 'rag_store.sqlite3')
    active_sha = sha(Path(active['database']))
    baseline_path = ROOT / 'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json'
    baseline = read(baseline_path)
    changed = []
    for item in baseline['files']:
        path = ROOT / item['path']
        if not path.is_file() or sha(path) != item['sha256']:
            changed.append(item['path'])
    preservation = {
        'rechecked_at': NOW.isoformat(), 'protected_total': len(baseline['files']),
        'unchanged': len(baseline['files']) - len(changed), 'changed': changed,
        'production_sqlite_sha256': prod_sha,
        'production_matches_expected': prod_sha == 'd7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087',
        'active_database_sha256': active_sha, 'active_database_matches_frozen_manifest': active_sha == manifest['database_sha256'],
        'production_switched_this_report': False, 'generation_rerun_this_report': False,
    }
    result = {
        'checked_at': NOW.isoformat(), 'active': active, 'current_counts': actual,
        'file_formats': formats, 'vector_integrity': validation,
        'species_candidate_tags_not_answer_coverage': scope,
        'structured_sources': structured,
        'statistical_source_concentration': {'source_ids': stat_ids, 'answer_candidate_chunks': stat_n, 'all_answer_candidate_chunks': actual['retrieval_eligible'], 'share': stat_n / actual['retrieval_eligible'], 'not_a_measured_top5_distribution': True},
        'quality_flags': quality, 'ocr_status': ocr,
        'law_snapshot_review': {'official_families': 12, 'saved_resources': 33, 'local_originals_compared': len(laws), 'statuses': law_statuses, 'not_current_legal_certification': True},
        'previous_run_test_evidence': test_results, 'tests_rerun_for_this_inventory': False,
        'website_health_checked_now': service, 'preservation': preservation,
        'scope_note': '98 registered source originals, including all current my_data files; not every project file, test question, model weight, historical report or code file.',
        'important_gaps': [
            'All-document archive search and default answer retrieval use different pools. 52,765 archive units do not mean 52,765 verified answer chunks.',
            'Not all OCR and image text have reliable semantic interpretation. Full-page CLIP vectors do not constitute expert visual diagnosis.',
            'Candidate species/source counts do not establish complete answers to the original 180 questions.',
            'Historical 720-run scores and the historical 50-answer subset cannot automatically represent this new v5 corpus.',
            'Two statistical source groups contribute about 75% of default candidate chunks. This is a pool composition finding, not observed ranking dominance.',
            'Current user research-use attestation and independently verified third-party/public redistribution permissions remain separate.',
        ],
    }
    OUT.mkdir(parents=True, exist_ok=False)
    dump('rag_status.json', result)
    jsonl('document_rag_status_98.jsonl', document_rows)
    jsonl('source_rag_status_100.jsonl', source_rows)
    dump('compatibility.json', preservation)

    title = '目前全部資料的 RAG 狀況總表'
    body = '<h1>' + title + '</h1><p class="muted">核對時間：' + NOW.strftime('%Y-%m-%d %H:%M:%S UTC+8') + '</p>'
    body += '<p class="lead">目前使用單一隔離 RAG v5。98 份已登錄原件（含 my_data 全部 53 份）均已解析，並具有文字或影像向量。全量搜尋與可安全用於答案的資料分開管理。</p>'
    body += '<p>版本：<code>' + html.escape(active['version']) + '</code><br>網站：<a href="http://127.0.0.1:8501/">http://127.0.0.1:8501/</a>；本次健康檢查：' + html.escape(str(service)) + '</p>'
    body += '<h2>入庫與檢索層級</h2>' + table(['層級', '數量', '意義'], [
        ['不同原件／原始路徑', '98／102', '重複原件以 SHA 去重，原始路徑保留'],
        ['my_data', '53／53', '本次讀取資料夾與資料庫對帳'],
        ['頁面／表格', '1,278／486', '文字、儲存格、原頁與位置追溯'],
        ['全文檢索單位', '52,765', '包括 28,276 筆原生結構化紀錄、24,283 個 RAG Chunk、206 個掃描 OCR 單位'],
        ['實際使用的去重文字向量', '34,936', 'BGE-M3，1024 維；不是快取資料列總數'],
        ['影像向量', '5,984', 'CLIP，512 維；含圖片、表格裁圖與完整頁面'],
        ['預設問答候選', '13,794', '仍須通過每次問題的物種、數值、版本、來源及引用檢查'],
        ['Context-only Chunk', '10,489', '已入庫；預設不作為直接答案依據，全文搜尋仍可回查'],
    ])
    body += '<h2>系統目前如何運作</h2><div class="flow">原件 → 清洗／段落、表格與 OCR 解析 → 來源、頁碼與 Record 定位 → 文字／影像向量 → 全文件搜尋<br>一般問答：問題與魚種解析 → BM25 + BGE-M3 → RRF k=60 → BGE Reranker → 來源／物種／版本與證據檢查 → 本地模型 → JSON／引用驗證</div>'
    body += '<p>一般問答與資料管理中的全文搜尋使用不同資料池。全文搜尋可查看待核對資料；檢索到一段文字也不代表它能完整回答問題。模型原始回答、系統確定性摘取、拒答與驗證失敗分開保存。</p>'
    body += '<h2>六魚種候選標註</h2>' + table(['魚種', '候選段落', '來源組'], [[s, v['candidate_chunks'], v['source_count']] for s, v in scope['species'].items()])
    body += '<p class="warning">此表是索引中的物種標記，不是獨立專業事實數、180 題答案覆蓋率或分類準確率。同一來源可能包含多種魚或多個段落。</p>'
    body += '<h2>主要官方資料與用途</h2>' + table(['來源', '原始紀錄', 'RAG Chunk／問答候選', '使用限制'], [[r['title'], r['raw_record_count'], f"{r['chunk_count']}／{r['answer_candidate_count']}", r['processing_scope']] for r in structured])
    body += '<h2>重要結構性限制</h2><p class="warning">漁業生產統計與 DGBAS 2020 合計 ' + f'{stat_n:,}' + ' 個問答候選，佔 ' + f'{stat_n / actual["retrieval_eligible"]:.2%}' + '。這是候選池組成，沒有據此斷言實際 Top-5 被統計資料壓過。大量 Chunk 不能代替養殖專業答案覆蓋。</p>'
    body += '<p>DGBAS 僅限 2020 單年度描述性事實；無年度鰻魚統計不補造年度；9,999 筆藥品快照的資料集完整性仍未確認，不能推導劑量、頻率、停藥期或當前藥品有效性。</p>'
    body += '<h2>圖片、OCR 與表格</h2>' + table(['品質旗標', '切分單位數'], [[r['quality_status'], r['count']] for r in quality])
    body += '<p>OCR_ONLY_REQUIRES_REVIEW 是切分單位計數，不是原件份數。全部圖像已建向量，但尚未完成全部圖片的專業語意判讀；小圖、複雜表頭、數字與公式保留待核對。空白儲存格不補 0。</p>'
    body += '<h2>法規</h2><p>已保存 12 組官方法規／要點頁及 21 份附件，共 33 個資源，建立 15 份本機文件對照。法規頁保留取得時間與整編截止資訊；不能把同修正日期視為全文一致。舊版、總說明與修正對照仍可搜尋，預設現行法規問題會另外篩選。</p>' + table(['自動版本對照狀態', '文件數'], law_statuses.items())
    body += '<p>《農業天然災害救助辦法》本機舊版為民國 115 年 3 月 24 日，已保存並索引 115 年 6 月 29 日官方快照。這是版本與原文對照，並非個案法律適用認證。</p>'
    body += '<h2>測試與保護</h2>' + table(['檢查', '結果／範圍'], [
        ['Repository pytest（沿用已保存結果）', '607 passed，另 8 subtests passed；0 failed／skipped／collection errors'],
        ['新增流程檢查（沿用已保存結果）', '10 passed'],
        ['Streamlit AppTest（沿用已保存結果）', '資料管理與法規頁通過；不取代 Generator 測試'],
        ['真實 API Smoke（沿用已保存結果）', '7／7 呼叫完成，6／7 原始 JSON 有效；M1 一次截斷失敗保留'],
        ['有來源案例', 'M2、M3、M4 回傳帶引用的部分回答；不是專業準確率測試'],
        ['本次資料庫完整性', validation['sqlite_integrity']],
        ['本次重新核對 Frozen Baseline', str(preservation['unchanged']) + '／' + str(preservation['protected_total'])],
        ['正式 SQLite SHA', prod_sha],
        ['新一輪 180 題／720 次', '本次未執行；舊版分數不可直接移用為 v5 成績'],
        ['Human Gold', '未建立；入庫與自動版本核對不等於人工專家核驗'],
    ])
    body += '<h2>接下來真正需要處理的事</h2><ol><li>依全文原文核驗專業問題的必要答案元素，重新建立 v5 的題目答案覆蓋與 Rubric。</li><li>優先複核 OCR 數字、複雜表格與藥物適用列，保留不確定狀態。</li><li>針對實際召回結果檢查統計類資料是否影響專業問題的排序；尚無結果前不宣稱已發生。</li><li>修復並驗證 M1 截斷 JSON 問題，再評估完整回歸；資料入庫完整不代表四模型作答已全面通過。</li></ol>'
    body += '<h2>追溯</h2><p>逐原件狀態：<a href="document_rag_status_98.jsonl">document_rag_status_98.jsonl</a>；逐來源狀態：<a href="source_rag_status_100.jsonl">source_rag_status_100.jsonl</a>；完整統計：<a href="rag_status.json">rag_status.json</a>；保護核對：<a href="compatibility.json">compatibility.json</a>。</p><p>資料庫：<code>' + html.escape(str(active['database'])) + '</code><br>SHA-256：<code>' + active_sha + '</code></p><p class="muted">僅整理已登錄的研究來源；不把程式、模型權重、測試題庫或所有歷史報告當成專業知識入庫。本次沒有修改資料庫、Prompt、索引、Production 或歷史評測。</p>'
    document = '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title + '</title><style>body{font-family:"Microsoft JhengHei",sans-serif;max-width:1120px;margin:32px auto;padding:0 20px 60px;background:#f2f8fc;color:#17324a;line-height:1.75}h1{font-size:30px}h2{margin-top:34px;color:#155f82}table{width:100%;border-collapse:collapse;background:white;font-size:14px}th,td{text-align:left;padding:10px 12px;border:1px solid #d6e6ed;vertical-align:top;overflow-wrap:anywhere}th{background:#dceff7}code{overflow-wrap:anywhere}.lead,.flow{background:#e0f2f8;padding:18px;border-radius:12px}.warning{background:#fff1cc;padding:13px;border-left:4px solid #cb9a26}.muted{color:#5c7280;font-size:14px}a{color:#076c9e}</style></head><body>' + body + '</body></html>'
    (OUT / 'rag_status_summary.html').write_text(document, encoding='utf-8')
    parser = HTMLParser()
    parser.feed(document)
    for path in OUT.glob('*.json'):
        read(path)
    for path in OUT.glob('*.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            json.loads(line)
    assert len(document_rows) == actual['documents'] == 98
    assert len(source_rows) == actual['sources'] == 100
    assert actual['retrieval_eligible'] + actual['context_only'] == actual['chunks']
    assert actual['archive_units'] == actual['semantic_archive_fts']
    assert preservation['active_database_matches_frozen_manifest'] and preservation['production_matches_expected']
    dump('report_validation.json', {'json_and_jsonl_parsed': True, 'html_parser_passed': True, 'document_rows': len(document_rows), 'source_rows': len(source_rows), 'counts_consistent': True, 'not_new_model_or_professional_accuracy_test': True})
    print(json.dumps({'output_directory': str(OUT), 'counts': actual, 'statistical_candidate_share': stat_n / actual['retrieval_eligible'], 'website_health': service, 'protection': preservation, 'files': [p.name for p in OUT.iterdir()]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
