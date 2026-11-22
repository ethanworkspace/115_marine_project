"""Stage reviewable changes; activation happens only after database validation."""
from pathlib import Path
import json,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'research_staging/unified_rag_v5_build_pointer.json').read_text(encoding='utf-8'));W=Path(P['workspace'])
APP=ROOT/'research_staging/app_sessions/launch_20261118_154253';stage=W/'app_staged';backup=W/'app_backup'
stage.mkdir(exist_ok=True);backup.mkdir(exist_ok=True)
for name in ('professional_platform.py','unified_question_engine.py','launch_info.json'):
    if not (backup/name).exists():shutil.copyfile(APP/name,backup/name)
text=(backup/'professional_platform.py').read_text(encoding='utf-8')
text=text.replace('from unified_question_engine import UnifiedQuestionRag','from unified_question_engine import UnifiedQuestionRag\nfrom src.unified_rag_v5.presentation import all_data_search,law_review')
text=text.replace('["知識問答","來源資料","資料管理","本次紀錄"]','["知識問答","來源資料","資料管理","法規核對","本次紀錄"]')
text=text.replace('{"來源資料":"來源資料庫","資料管理":"文件與多媒體資料","本次紀錄":"本次問答紀錄"}', '{"來源資料":"來源資料庫","資料管理":"文件與多媒體資料","法規核對":"官方法規版本核對","本次紀錄":"本次問答紀錄"}')
text=text.replace('elif page=="資料管理":','elif page=="法規核對":\n    law_review(runtime)\nelif page=="資料管理":',1)
text=text.replace('    labels={"EXISTING_ADMITTED_STRUCTURED_RECORD_SCOPE"', '    all_data_search(runtime)\n    labels={"USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT":"依本輪使用聲明供本機研究使用","OFFICIAL_STATUTORY_SNAPSHOT_ART9":"已保存官方條文／附件快照","EXISTING_ADMITTED_STRUCTURED_RECORD_SCOPE"',1)
text=text.replace('所有原件皆已登錄。可供問答的範圍另依使用依據、魚種、版本與解析品質檢查；存入文件庫不等同全文可直接作答。','所有原件已入庫並建立文字或影像向量。問答仍檢查魚種、數值、版本與解析品質；掃描或表格待核對內容可在全部資料搜尋中回查。')
text=text.replace('else "查閱這次啟動期間留下的回答與來源紀錄。")','else "核對官方版本、條文與原始附件，保留本機舊版差異。" if page=="法規核對" else "查閱這次啟動期間留下的回答與來源紀錄。")',1)
text=text.replace('b.metric("可檢索段落",','b.metric("問答候選段落",')
text=text.replace('    all_data_search(runtime)','    extra_a,extra_b=st.columns(2)\n    extra_a.metric("全文索引片段",f\'{summary["archive_units"]:,}\')\n    extra_b.metric("去重文字向量",f\'{summary["distinct_text_vectors_used"]:,}\')\n    all_data_search(runtime)',1)
text=text.replace("e.kind='IMAGE' AND a.width", "e.kind IN ('IMAGE','PAGE_RENDER') AND a.width")
text=text.replace('預覽前12張符合尺寸條件的圖片；原始文件仍保留完整圖文。','預覽前12張圖片或原頁影像；整頁影像也保留向量圖、圖表與版面，原始文件不變。')
assert 'law_review(runtime)' in text and 'all_data_search(runtime)' in text
(stage/'professional_platform.py').write_text(text,encoding='utf-8')
adapter=(backup/'unified_question_engine.py').read_text(encoding='utf-8')
adapter=adapter.replace('from src.unified_rag_v4.retrieval import UnifiedRetriever','from src.unified_rag_v5.retrieval import UnifiedRetriever')
adapter=adapter.replace('unified-v4-program-owned-citations-20261120-v3','unified-v5-all-documents-law-verified-20261121-v1')
adapter=adapter.replace("        prompt+='\\n魚種：'", "        prompt+='\\n查詢時間：'+str(r.get('at','未記載'))+'\\n法規以所列官方快照及整編截止日為準；同名機關改制、施行日期及個案適用條件不明時須說明缺口，不把歷史條文直接當成今天的個案建議。'\n        prompt+='\\n魚種：'",1)
old="        if error: validation['raw_validation_reason']=error\n        return result,validation"
new="""        if error: validation['raw_validation_reason']=error
        if result['answer_status']=='VALIDATION_FAILED' and evidence.get('qualified_contexts'):
            result['final_answer']='已找到候選來源，但本次模型回覆未通過引用、格式或數值支持檢查，因此暫不列為已核實答案。可查看原始資料，或調整問題後重新查詢。這不代表資料庫沒有相關內容。'
            flags['source_availability_not_conflated_with_model_validation_failure']=True
        return result,validation"""
assert old in adapter;adapter=adapter.replace(old,new,1)
(stage/'unified_question_engine.py').write_text(adapter,encoding='utf-8')
print(json.dumps({'staged':str(stage),'backup':str(backup),'active_app_unchanged_until_activation':True}))
