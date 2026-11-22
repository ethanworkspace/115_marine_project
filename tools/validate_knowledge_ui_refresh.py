"""Exercise the actual Streamlit presentation and isolated note persistence."""
import ast, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT/'research_staging/app_sessions/launch_20261118_154253'
OUT = Path(json.loads((ROOT/'research_staging/knowledge_ui_refresh_pointer.json').read_text(encoding='utf-8'))['directory'])
sys.path[:0] = [str(APP),str(ROOT)]
os.environ['MARINE_NOTES_PATH'] = str(OUT/'ui_test_notes.sqlite3')
from knowledge_notes import KnowledgeNotes

checks = {}
for name in ('knowledge_platform.py','knowledge_notes.py'):
    ast.parse((APP/name).read_text(encoding='utf-8'))
checks['syntax'] = True
store = KnowledgeNotes(OUT/'store_test_notes.sqlite3')
note_id = store.save('水質紀錄測試','時間08:30；溶氧單位mg/L。\n這是介面測試資料，不是養殖建議。','吳郭魚','水質環境',origin='SAVED_RAG_ANSWER',provenance={'question_id':'UI-TEST','answer_origin':'MODEL_GENERATED'})
assert KnowledgeNotes(store.path).get(note_id)['body'].startswith('時間08:30')
assert len(store.list('mg/l',species='吳郭魚',topic='水質環境'))==1
assert not store.list(species='烏魚')
before = store.get(note_id)
store.save('更新的測試筆記','保留來源關係與建立時間。','吳郭魚','水質環境',note_id=note_id)
after = store.get(note_id)
assert before['created_at']==after['created_at'] and before['provenance_json']==after['provenance_json']
assert after['origin']=='SAVED_RAG_ANSWER'
try: store.save(' ','')
except ValueError: checks['empty_note_rejected']=True
else: raise AssertionError('Empty note accepted')
checks['notes_persistence_search_species_and_edit']=True

from streamlit.testing.v1 import AppTest
app = AppTest.from_file(str(APP/'knowledge_platform.py'),default_timeout=300).run(timeout=300)
def healthy(stage):
    errors = [x.message for x in app.exception]
    assert not errors, (stage,errors)
    checks[stage] = True
healthy('chat_page')
assert not app.button(key='free_answer').disabled
app.button(key='free_answer').click().run(timeout=300)
assert any('先寫下你的問題' in x.value for x in app.warning)
healthy('empty_question_does_not_start_generator')
nav_labels = [app.button(key='nav_'+k).label for k in ('chat','knowledge','history')]
assert nav_labels==['知識問答','小知識','本次紀錄']
assert not any(x.label in ('來源資料','資料來源','資料管理','法規核對','法規資料') for x in app.button)
checks['navigation_has_only_three_requested_pages']=True
app.button(key='suggestion_1').click().run(timeout=300)
assert app.text_area(key='platform_free_question').value=='水質量測紀錄應包含哪些資訊？'
assert not app.button(key='free_answer').disabled
healthy('suggested_question_prefill')
app.button(key='nav_knowledge').click().run(timeout=300)
healthy('notes_page')
app.button(key='new_note').click().run(timeout=300)
app.text_input(key='note_title').set_value('介面驗證用小知識')
app.text_area(key='note_body').set_value('這是測試資料，僅寫入獨立測試筆記庫。')
app.selectbox(key='note_species').select('烏魚')
app.selectbox(key='note_topic').select('魚種認識')
app.button(key='FormSubmitter:knowledge_note_form-儲存小知識').click().run(timeout=300)
healthy('create_note_form')
new = next(r for r in KnowledgeNotes().list() if r['title']=='介面驗證用小知識')
assert new['species']=='烏魚'
app.button(key='edit_'+new['note_id']).click().run(timeout=300)
app.text_input(key='note_title').set_value('已編輯的小知識')
app.button(key='FormSubmitter:knowledge_note_form-儲存小知識').click().run(timeout=300)
healthy('edit_note_form')
assert KnowledgeNotes().get(new['note_id'])['title']=='已編輯的小知識'
app.text_input(key='notes_query').set_value('不存在的關鍵字').run(timeout=300)
assert any('沒有符合條件' in x.value for x in app.info)
healthy('notes_search_empty_state')
app.button(key='nav_history').click().run(timeout=300)
healthy('history_page')
if any(b.key=='collect_answer' for b in app.button):
    app.button(key='collect_answer').click().run(timeout=300)
    healthy('save_answer_opens_note_draft')
    assert app.text_area(key='note_body').value.strip()
    assert app.text_input(key='note_title').value.strip()
app.button(key='nav_chat').click().run(timeout=300)
healthy('return_to_chat')
app.radio(key='platform_question_mode').set_value('挑選問題').run(timeout=300)
healthy('question_bank_page')
assert len(app.selectbox(key='platform_question').options)==180
checks['original_180_questions_unchanged']=True

report={'status':'PASS','checks':checks,'new_ui_pages':nav_labels,
    'app_test_generator_mocked':False,'app_test_generator_called':False,
    'note_tests_use_separate_databases':True,'test_database':str(OUT/'ui_test_notes.sqlite3'),
    'engine_changes':False,'not_a_new_model_evaluation':True}
(OUT/'streamlit_functional_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
