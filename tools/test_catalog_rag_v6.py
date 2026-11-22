"""Run actual retrieval, image vectors, isolated UI and small API smoke."""
from __future__ import annotations
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'research_staging/app_sessions/launch_20261118_154253'
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(APP)]
import complete_and_catalog_rag_v6 as b
w,r,cfg=b.paths()
if '--reuse-ui' in sys.argv:
    ui=b.read(r/'streamlit_validation.json')
else:
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(str(APP/'professional_platform.py'),default_timeout=300).run(timeout=300)
    ui={'initial_exceptions':[x.message for x in at.exception],'generator_mocked':False,'generator_invoked_by_apptest':False}
    at.radio(key='platform_page').set_value('資料管理').run(timeout=300)
    ui['data_exceptions']=[x.message for x in at.exception];ui['metrics']=[{'label':x.label,'value':x.value} for x in at.metric]
    ui['classification_table_present']=any(len(x.value)==98 and '分類' in x.value.columns for x in at.dataframe)
    at.radio(key='platform_page').set_value('法規核對').run(timeout=300)
    ui['law_exceptions']=[x.message for x in at.exception];ui['law_rows']=len(at.dataframe[0].value) if at.dataframe else 0
    ui['passed']=not any(ui[k] for k in ('initial_exceptions','data_exceptions','law_exceptions')) and ui['law_rows']==12 and ui['classification_table_present']
    b.dump(r/'streamlit_validation.json',ui)
assert ui['passed'],ui
b.emit({'stage':'AppTest','passed':True})
import answer_policy,free_question_engine,unified_question_engine
for module in (answer_policy,free_question_engine,unified_question_engine):module.SESSION=w/'live_smoke'
for folder in ('prompts','streams','free_queries'):(w/'live_smoke'/folder).mkdir(exist_ok=True)
runtime=unified_question_engine.UnifiedQuestionRag()
text=runtime.unified.search_archive('鰻魚池塘清理消毒的原始文獻')
assert text and all(x['document_id'] for x in text)
images=runtime.unified.search_images('鰻魚寄生蟲顯微圖片','鰻魚',limit=6)
assert len(images)==6 and all(Path(x['path']).is_file() and x.get('source_positions') for x in images)
retrieval=runtime.prepare_free_question('虱目魚養殖文獻提到哪些養殖方式？','虱目魚')
assert retrieval['top5'] and retrieval['retrieval']['corpus_version']==cfg['version']
b.dump(r/'retrieval_and_visual_validation.json',{'corpus_version':cfg['version'],'database_sha256':runtime.unified.sha,'real_bge_archive_search':True,'archive_search_results':text,'real_clip_image_search':True,'image_results':images,'image_vectors_loaded':len(runtime.unified.image_rows),'actual_reranker_top5':retrieval['top5'],'not_expert_accuracy':True})
b.emit({'stage':'real_retrieval_and_image','passed':True,'images':len(runtime.unified.image_rows),'top5':len(retrieval['top5'])})
empty=copy.deepcopy(retrieval);empty['question_id']='V6-CONTROLLED-EMPTY';empty['top5']=[];empty['source_group_ids']=[]
from src.unified_rag_v4.common import digest
empty['context_digest']=digest([])
cases=[('SOURCE_BOUND_POSITIVE',retrieval),('CONTROLLED_EMPTY_CONTEXT',empty)]
records=[];path=r/'real_api_smoke.jsonl'
if path.exists():records=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
done={x['case'] for x in records}
for case,q in cases:
    if case in done:continue
    raw=runtime.call(copy.deepcopy(q),'M2',stage='UNIFIED_V6_CATALOG_REAL_SMOKE')
    result=raw['result'];row={'case':case,'model_id':'M2','api_completed':raw['api_completed'],'raw_json_valid':result['validation_status'].get('raw_json_valid'),'answer_status':result['answer_status'],'answer_origin':result['answer_origin'],'citations':result['supporting_chunk_ids'],'full_record':raw}
    records.append(row)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    b.emit({k:v for k,v in row.items() if k!='full_record'})
summary={'calls':len(records),'api_completed':sum(bool(x['api_completed']) for x in records),'raw_json_valid':sum(bool(x['raw_json_valid']) for x in records),'results':[{k:v for k,v in x.items() if k!='full_record'} for x in records],'not_professional_accuracy':True,'not_a_720_run':True}
b.dump(r/'rag_real_e2e_validation.json',summary)
assert all(x['api_completed'] for x in records)
assert next(x for x in records if x['case']=='CONTROLLED_EMPTY_CONTEXT')['answer_status'] in ('INSUFFICIENT_EVIDENCE','VALIDATION_FAILED')
