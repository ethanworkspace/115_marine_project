import json
from pathlib import Path

def all_data_search(runtime):
    import streamlit as st
    with st.expander('搜尋全部文件與原始紀錄'):
        text=st.text_input('輸入要找的資料',key='archive_search_text',placeholder='例如：石斑魚放養、水質測定、鰻魚鰓部圖片')
        st.caption('搜尋包含全文、原始資料列與待核對 OCR。找到資料不代表它已符合專業回答條件。')
        if st.button('搜尋資料庫',key='archive_search_button',disabled=not text.strip()):
            with st.spinner('正在搜尋文件與向量資料庫…'):
                st.session_state['archive_search_hits']=runtime.unified.search_archive(text)
        for row in st.session_state.get('archive_search_hits',[]):
            with st.expander((row.get('title') or '原始紀錄')+' · '+row['kind']):
                st.write(row['text'])
                try:locator=json.loads(row['locator'])
                except (json.JSONDecodeError,TypeError):locator={'原始紀錄位置':row['locator']}
                if isinstance(locator,dict):
                    pages=locator.get('physical_pages',locator.get('pages'))
                    if pages and any(p is not None for p in pages):
                        st.caption('原文頁碼：'+ '–'.join(str(p) for p in dict.fromkeys(pages) if p is not None))
                    elif '原始紀錄位置' in locator:st.caption(str(locator['原始紀錄位置']))
                with st.expander('來源識別與精確定位'):
                    st.caption('文件識別：'+str(row['document_id'])+'；資料片段：'+row['unit_id'])
                    st.json(locator)

def law_review(runtime):
    import streamlit as st
    report=Path(runtime.unified.config['report_directory'])
    laws=json.loads((report/'official_laws_parsed.json').read_text(encoding='utf-8'))
    rows=json.loads((report/'local_law_version_comparison.json').read_text(encoding='utf-8'))
    st.caption('以下為本輪取得的官方條文快照與本機文件對照。整編截止日、公布日、施行日與實際個案適用時間須分別確認。')
    st.dataframe([{'法規':x['title'],'官方列示版本':x['official_version'],'條文／要點數':len(x['articles']),
        '官方整編截止':x.get('official_compilation_cutoff') or '原頁未列明','官方來源':x['source']['url']} for x in laws.values()],hide_index=True,width='stretch')
    labels={'VERSION_DATE_DIFFERS':'本機版本日期不同','VERSION_DATE_MATCH_TEXT_CHECK_RECORDED':'日期相同，保留內文差異待查',
        'OFFICIAL_DATE_AND_ALL_ARTICLES_MATCH':'日期及條文正規化比對一致','OFFICIAL_ATTACHMENT_BYTES_MATCH':'與官方附件原始檔完全相符',
        'EXPLANATION_OR_COMPARISON_NOT_CURRENT_NORMATIVE_TEXT':'說明／對照資料，非現行條文','VERSION_NOT_FULLY_ESTABLISHED':'原件版本仍需進一步核對'}
    for row in rows:
        with st.expander(row['title']+' · '+labels.get(row['verification_status'],row['verification_status'])):
            st.write('原件版本：'+str(row['original_version'])+'；官方版本：'+str(row['official_version']))
            st.caption('已比較 '+str(row['compared_articles'])+' 條；正規化文字一致 '+str(row['matching_articles'])+' 條。其餘可能含版面、段落編號或實質文字差異，未一律判定法規已變更。')
            st.markdown('[查看官方條文]('+row['official_url']+')')
            changes=[x for x in row['article_comparisons'] if x['status']!='NORMALIZED_TEXT_MATCH']
            for item in changes[:4]:
                st.write(item['article']);left,right=st.columns(2)
                with left:st.caption('本機原文');st.write(item['local_text'])
                with right:st.caption('官方原文');st.write(item['official_text'])
            st.caption('完整逐條比對保存在本輪核對報告；不以殘留容許量推導許可劑量或停藥日數。')
