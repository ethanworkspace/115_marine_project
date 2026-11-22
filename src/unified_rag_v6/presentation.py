"""Source catalog and honest visual discovery in the isolated research app."""
from src.unified_rag_v5.presentation import all_data_search,law_review


def organized_source_catalog(runtime):
    import streamlit as st
    st.caption('原始文件、圖片、表格與清洗片段已集中複製至 my_data／RAG來源資料總庫；原位置仍保留。')
    with runtime.unified.connect() as con:
        rows=[dict(r) for r in con.execute('SELECT title,category,species_json,catalog_path FROM catalog_documents ORDER BY category,title')]
    with st.expander('查看分類後的來源位置'):
        st.dataframe([{'文件':r['title'],'分類':r['category'],'文內魚種標記':r['species_json'],'集中保存位置':r['catalog_path']} for r in rows],hide_index=True,width='stretch')
    with st.expander('搜尋圖片與原頁影像'):
        text=st.text_input('描述要找的圖片',key='v6_visual_text',placeholder='例如：鰻魚寄生蟲顯微圖片')
        fish=st.selectbox('圖片來源魚種提示',['鰻魚','虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','通用養殖'],key='v6_visual_species')
        st.caption('使用影像向量找候選圖片；相似度不是疾病診斷、魚種辨識或答案支持的驗證。')
        if st.button('搜尋圖片',key='v6_visual_search',disabled=not text.strip()):
            with st.spinner('正在搜尋影像向量…'):st.session_state['v6_visual_hits']=runtime.unified.search_images(text,fish)
        for row in st.session_state.get('v6_visual_hits',[]):
            positions=row.get('source_positions',[])
            title=positions[0]['title'] if positions else '來源待核對圖片'
            with st.expander(title+' · '+row['asset_id']):
                st.image(row['path'],width='stretch')
                st.caption('OCR：'+str(row['ocr_status'])+'；僅作圖片查找，不是專業判圖。')
                st.dataframe([{'文件':p['title'],'原頁':p['page'],'類型':p['kind']} for p in positions],hide_index=True,width='stretch')
                if row['ocr_text']:st.text(row['ocr_text'])
