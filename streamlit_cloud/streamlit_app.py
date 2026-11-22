"""Question-first watercolor interface for the existing isolated RAG."""
from __future__ import annotations
import base64
import json
import sys
from html import escape
from pathlib import Path

sys.dont_write_bytecode = True
SESSION = Path(__file__).resolve().parent
sys.path.insert(0, str(SESSION))
import streamlit as st
from cloud_client import get_client, RemoteNotes as KnowledgeNotes, TOPICS, SPECIES as NOTE_SPECIES, gate, safe_answer_markdown

MODELS = {'M2':'Qwen2.5 Coder · 7B'}
CATEGORIES = {'Fact':'養殖知識','Water Quality':'水質環境','Disease':'疾病防治','Climate / Cold':'氣候防寒','Medication / Law':'用藥規範','Calculation':'養殖計算'}
FISH = ['虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']
NAV = [('知識問答','chat'),('小知識','knowledge'),('本次紀錄','history')]
st.set_page_config(page_title='Aquaculture Knowledge Platform',page_icon=str(SESSION/'assets/aquaculture_fish_favicon_v1.png'),layout='wide',initial_sidebar_state='auto')

@st.cache_data(show_spinner=False)
def asset_uri(filename):
    return 'data:image/png;base64,' + base64.b64encode((SESSION/'assets'/filename).read_bytes()).decode('ascii')

ICONS = {name:asset_uri('watercolor_'+name+'.png') for _,name in NAV}
styles = (SESSION/'platform_watercolor.css').read_text(encoding='utf-8')
styles = styles.replace('__OCEAN_BACKGROUND__',asset_uri('ocean_watercolor_chibi_background.png'))
for name,uri in ICONS.items(): styles = styles.replace('__ICON_'+name.upper()+'__',uri)
st.markdown('<style>'+styles+'</style>',unsafe_allow_html=True)

def load(corpus_version=None):
    return get_client()

@st.cache_data(show_spinner=False, ttl=30)
def load_content(corpus_version=None, workspace=None):
    return get_client().bootstrap()

@st.cache_data(ttl=1, show_spinner=False)
def history():
    return get_client().history()

def html(content):
    st.markdown(content,unsafe_allow_html=True)

def section(title, note=''):
    html('<div class="section-label">'+escape(title)+'</div>'+('<div class="section-note">'+escape(note)+'</div>' if note else ''))

def navigate(page):
    st.session_state['platform_page'] = page

def suggest_question(text):
    st.session_state.update(platform_free_question=text,platform_question_mode='自由提問',platform_page='知識問答')

def record_details(record):
    qid = record.get('question_id','')
    return record.get('question_payload') or questions.get(qid) or {'question':record.get('question',qid),'species':record.get('species',''),'top5':[]}

def open_note(note=None, draft=None):
    draft = note or draft or {}
    st.session_state.update(notes_editor_open=True,notes_edit_id=draft.get('note_id'),
        note_title=draft.get('title',''),note_body=draft.get('body',''),
        note_species=draft.get('species','通用') if draft.get('species','通用') in NOTE_SPECIES else '通用',
        note_topic=draft.get('topic','其他') if draft.get('topic','其他') in TOPICS else '其他',
        note_provenance=draft.get('provenance',{}),note_origin=draft.get('origin','PERSONAL_NOTE'))

def collect_answer(record):
    info = record_details(record)
    category = CATEGORIES.get(info.get('category'),'其他')
    topic = {'養殖知識':'養殖管理','疾病防治':'疾病觀察'}.get(category,category)
    draft = {'title':info.get('question','本次問答')[:80], 'body':record['result']['final_answer'][:8000],
        'species':info.get('species','通用'),'topic':topic,'origin':'SAVED_RAG_ANSWER',
        'provenance':{'question_id':record.get('question_id'),'model_id':record.get('model_id'),
            'answer_origin':record['result'].get('answer_origin'),'answer_status':record['result'].get('answer_status'),
            'context_digest':record.get('context_digest'),'supporting_chunk_ids':record['result'].get('supporting_chunk_ids',[])}}
    open_note(draft=draft)
    navigate('小知識')

def show_citations(record):
    info = record_details(record)
    contexts = {c['chunk_id']:c for c in info.get('top5',[])}
    ids = [cid for cid in dict.fromkeys(record['result'].get('supporting_chunk_ids',[])) if cid in contexts]
    if not ids:
        st.caption('本次沒有通過驗證的引用段落。')
        return
    with st.expander('查看回答引用 · '+str(len(ids))+'段'):
        for number,cid in enumerate(ids,1):
            c = contexts[cid]
            source = sources.get(c['source_id'],{})
            checks = record['result'].get('validation_status',{}).get('exact_quote_checks',[])
            quotes = [x['quote'] for x in checks if x.get('chunk_id')==cid and x.get('quote_verified')]
            quote = '\n\n'.join(quotes) if quotes else c.get('source_quote','')
            html('<div class="source-title">'+str(number)+'. '+escape(source.get('title') or c['source_id'])+'</div><div class="source-quote">'+escape(quote)+'</div><div class="source-location">'+escape(str(c.get('source_version','')))+' · '+escape(str(c.get('exact_locator','')))+'</div>')
            if source.get('attribution'): st.caption(str(source['attribution']))
            for asset in c.get('media_assets',[])[:2]:
                if asset.get('remote_asset_id'):
                    picture=get_client().image(asset['remote_asset_id'])
                    if picture: st.image(picture,caption='引用原文 · 第'+str(asset.get('page',''))+'頁')

def show_answer(record):
    result = record['result']
    status = result.get('answer_status','VALIDATION_FAILED')
    label,style = {'ANSWERED_GROUNDED':('有據回答',''),'ANSWERED_PARTIAL':('部分資訊','partial'),
        'INSUFFICIENT_EVIDENCE':('資訊待補','guide'),'VALIDATION_FAILED':('待核對','guide')}.get(status,('待核對','guide'))
    html('<div class="answer-head"><span class="answer-title">給你的回答</span><span class="badge '+style+'">'+label+'</span></div>')
    info = record_details(record)
    html('<div class="answer-question">'+escape(info.get('question',record.get('question_id','')))+'</div>')
    if record.get('api_error'): st.warning('模型連線未完成，以下保留本次資訊缺口說明。')
    st.markdown(safe_answer_markdown(result.get('final_answer','本次未取得可顯示的回答。')),unsafe_allow_html=False)
    origins = {'MODEL_GENERATED':'模型回答','DETERMINISTIC_EVIDENCE_EXTRACTION':'來源內容摘取',
        'SYSTEM_GUIDANCE':'查核說明','ABSTAINED':'資訊缺口說明','VALIDATION_FAILED':'輸出待核對'}
    origin = result.get('answer_origin','')
    html('<div class="answer-meta">'+escape(MODELS.get(record['model_id'],record['model_id']))+' · '+escape(origins.get(origin,origin))+'</div>')
    if result.get('missing_information'):
        with st.expander('尚需補充的資訊'):
            for item in result['missing_information']: st.markdown(safe_answer_markdown('- '+str(item)),unsafe_allow_html=False)
    show_citations(record)
    left,right = st.columns(2)
    with left:
        st.button('收藏為小知識',key='collect_answer',on_click=collect_answer,args=(record,),width='stretch')
    with right:
        export = '# 水產養殖問答\n\n'+info.get('question','')+'\n\n'+result.get('final_answer','')+'\n\n回答形式：'+origins.get(origin,origin)
        st.download_button('下載回答',export,file_name=record['question_id']+'_answer.md',mime='text/markdown',key='download_answer',width='stretch')

def heading(title,description,icon):
    html('<div class="page-heading"><img src="'+ICONS[icon]+'" alt=""><div><h1>'+escape(title)+'</h1><p>'+escape(description)+'</p></div></div>')

gate()

try:
    active = {'version':'remote-current-rag-v6','workspace':''}
    questions,sources = load_content(active['version'],active['workspace'])
except Exception as exc:
    st.title('Aquaculture Knowledge Platform')
    st.error('問答服務暫時無法載入，請稍後再試。')
    with st.expander('連線資訊'): st.code(str(exc))
    st.stop()

if st.session_state.get('platform_page') not in [p for p,_ in NAV]: st.session_state['platform_page']='知識問答'
if st.session_state.get('platform_question_mode') not in ['自由提問','挑選問題']: st.session_state['platform_question_mode']='自由提問'
page = st.session_state['platform_page']

with st.sidebar:
    html('<div class="brand"><img src="'+ICONS['chat']+'" alt=""><div><div class="brand-name">Aquaculture<br>Knowledge Platform</div><div class="brand-sub">養殖漁業知識平台</div></div></div>')
    html('<div class="sidebar-label">探索與記錄</div>')
    for name,icon in NAV:
        st.button(name,key='nav_'+icon,on_click=navigate,args=(name,),type='primary' if page==name else 'secondary',width='stretch')
    st.divider()
    with st.expander('問答偏好'):
        species = st.selectbox('養殖魚種',['全部魚種']+FISH,key='platform_species',format_func=lambda s:'自動辨識魚種' if s=='全部魚種' else s)
        model = st.selectbox('回答模型',list(MODELS),index=0,key='platform_model',format_func=lambda m:MODELS[m])
        html('<div class="model-note">也可以直接在問題中說明魚種、場域與條件。</div>')
    html('<div class="side-foot">一個問題，一點新發現。<br><small>M2與知識服務於本機運作</small></div>')

if page=='知識問答':
    html('<div class="hero"><div><div class="eyebrow">A LITTLE KNOWLEDGE, EVERY DAY</div><h1>養殖疑問，慢慢聊清楚。</h1><p>從日常管理到水質環境，提出你的問題，<br>一起找出有依據的答案。</p></div><img src="'+ICONS['chat']+'" alt="淡藍水彩魚兒對話圖示"></div>')
    left,right = st.columns([2.5,1],gap='large')
    record = None
    with left:
        with st.container(border=True,key='query_panel'):
            section('今天想了解什麼？','說明魚種與遇到的情況，能幫助找到更合適的內容。')
            mode = st.radio('提問方式',['自由提問','挑選問題'],horizontal=True,key='platform_question_mode',label_visibility='collapsed')
            if mode=='自由提問':
                text = st.text_area('你的養殖問題',placeholder='例如：虱目魚寒流來時，魚塭有哪些操作應避免？',height=140,max_chars=2000,key='platform_free_question',label_visibility='collapsed')
                if st.button('開始問答',key='free_answer',type='primary',width='stretch'):
                    if not text.strip():
                        st.warning('先寫下你的問題，再開始問答。')
                    else:
                        try:
                            with st.spinner('正在閱讀相關知識，整理回答…'):
                                st.session_state['last']=load(active['version']).call_free(text,model,selected_species=species)
                            history.clear()
                        except Exception as exc:
                            st.error('本次問答未完成，請稍後再試。')
                            with st.expander('連線資訊'): st.code(str(exc))
                last = st.session_state.get('last')
                if last and last['question_id'].startswith('FREE-') and last['model_id']==model: record=last
            else:
                topic = st.selectbox('問題主題',['全部主題']+list(CATEGORIES),format_func=lambda c:CATEGORIES.get(c,c),key='platform_topic_v2')
                search = st.text_input('搜尋問題',placeholder='水溫、投餌、放養密度…',key='platform_search')
                filtered = [qid for qid,q in questions.items() if (species=='全部魚種' or q['species']==species)
                    and (topic=='全部主題' or q.get('category')==topic) and (not search.strip() or search.strip().casefold() in q['question'].casefold())]
                if filtered:
                    if st.session_state.get('platform_question') not in filtered: st.session_state['platform_question']=filtered[0]
                    qid = st.selectbox('選擇問題',filtered,format_func=lambda q:questions[q]['question'],key='platform_question')
                    q = questions[qid]
                    html('<div class="question-preview"><span class="chip">'+escape(q['species'])+'</span><span class="chip chip-muted">'+escape(CATEGORIES.get(q.get('category'),'養殖知識'))+'</span><p>'+escape(q['question'])+'</p></div>')
                    if st.button('開始問答',key='answer',type='primary',width='stretch'):
                        try:
                            with st.spinner('正在整理回答…'): st.session_state['last']=load(active['version']).call(q,model,stage='INTERACTIVE_KNOWLEDGE_PLATFORM')
                            history.clear()
                        except Exception as exc:
                            st.error('本次問答未完成，請稍後再試。')
                            with st.expander('連線資訊'): st.code(str(exc))
                    last = st.session_state.get('last')
                    if last and last['question_id']==qid and last['model_id']==model: record=last
                else: st.info('沒有符合條件的問題，可以改用自由提問。')
        if record:
            with st.container(border=True,key='answer_panel'): show_answer(record)
        else:
            html('<div class="mini-heading">讓問題更清楚的小提醒</div><div class="tips-grid"><div class="tip"><span>01 / 魚種</span><strong>先說明養殖對象</strong><p>不同品種的資訊，適用範圍可能不同。</p></div><div class="tip"><span>02 / 情境</span><strong>補上現場的條件</strong><p>例如季節、養殖方式與已觀察到的狀況。</p></div><div class="tip"><span>03 / 紀錄</span><strong>保留數值與單位</strong><p>有量測資料時，一併附上時間與單位。</p></div></div>')
    with right:
        with st.container(border=True,key='quick_panel'):
            html('<img class="quick-icon" src="'+ICONS['knowledge']+'" alt=""><div class="quick-title">把新發現，慢慢收集。</div><div class="quick-copy">把值得記住的內容存成小卡，<br>下次需要時，輕鬆找回。</div>')
            st.button('看看我的小知識',key='go_notes',on_click=navigate,args=('小知識',),width='stretch')
            st.divider()
            section('也可以這樣問')
            for i,prompt in enumerate(['虱目魚寒流前可以先確認哪些事項？','水質量測紀錄應包含哪些資訊？','石斑魚的日常養殖管理有哪些重點？']):
                st.button(prompt,key='suggestion_'+str(i),on_click=suggest_question,args=(prompt,),width='stretch')

elif page=='小知識':
    heading('我的小知識','把值得記住的養殖知識，整理成自己的小卡。','knowledge')
    try:
        notes = KnowledgeNotes()
    except Exception:
        st.error('小知識目前無法儲存，請稍後再試；原有紀錄不會被覆寫。')
        st.stop()
    if st.session_state.pop('notes_reset_filters',False):
        st.session_state.update(notes_query='',notes_filter_species='全部魚種',notes_filter_topic='全部主題')
    if st.session_state.pop('notes_saved',False): st.success('小知識已保存。')
    search_col,add_col = st.columns([3,1])
    with search_col: query = st.text_input('搜尋小知識',placeholder='找找標題或內容…',key='notes_query',label_visibility='collapsed')
    with add_col: st.button('新增小知識',key='new_note',type='primary',width='stretch',on_click=open_note)
    if st.session_state.get('notes_editor_open'):
        with st.container(border=True,key='note_editor'):
            section('編輯小知識' if st.session_state.get('notes_edit_id') else '記下一點新知識','這裡是你的個人筆記，可隨時修改。')
            with st.form('knowledge_note_form'):
                st.text_input('標題',max_chars=80,key='note_title',placeholder='例如：今天的水質觀察')
                c1,c2 = st.columns(2)
                with c1: st.selectbox('魚種',NOTE_SPECIES,key='note_species')
                with c2: st.selectbox('主題',TOPICS,key='note_topic')
                st.text_area('小知識內容',height=180,max_chars=8000,key='note_body',placeholder='記下觀察、重點，或想繼續了解的問題。')
                save = st.form_submit_button('儲存小知識',type='primary',width='stretch')
                if save:
                    try:
                        notes.save(st.session_state['note_title'],st.session_state['note_body'],
                            st.session_state['note_species'],st.session_state['note_topic'],
                            note_id=st.session_state.get('notes_edit_id'),origin=st.session_state.get('note_origin','PERSONAL_NOTE'),
                            provenance=st.session_state.get('note_provenance',{}))
                        st.session_state.update(notes_editor_open=False,notes_saved=True,notes_reset_filters=True)
                        st.rerun()
                    except ValueError as exc: st.warning(str(exc))
                    except Exception: st.error('這次未能儲存，已保留輸入內容，請稍後再試。')
            st.button('取消編輯',key='cancel_note',on_click=lambda:st.session_state.update(notes_editor_open=False))
    f1,f2 = st.columns(2)
    with f1: note_fish = st.selectbox('依魚種篩選',['全部魚種']+NOTE_SPECIES,key='notes_filter_species')
    with f2: note_topic = st.selectbox('依主題篩選',['全部主題']+TOPICS,key='notes_filter_topic')
    records = notes.list(query,note_fish,note_topic)
    html('<div class="note-count">'+str(len(records))+' 張小知識</div>')
    if records:
        for start in range(0,len(records),3):
            columns = st.columns(3,gap='medium')
            for col,note in zip(columns,records[start:start+3]):
                with col:
                    with st.container(border=True,key='note_card_'+note['note_id']):
                        saved = note['origin']=='SAVED_RAG_ANSWER'
                        html('<div class="note-kicker"><img src="'+ICONS['knowledge']+'" alt="">'+('問答收藏' if saved else '我的筆記')+'</div><div class="note-title">'+escape(note['title'])+'</div><span class="chip">'+escape(note['species'])+'</span><span class="chip chip-muted">'+escape(note['topic'])+'</span><div class="note-body">'+escape(note['body'])+'</div><div class="note-date">更新於 '+escape(note['updated_at'][:16].replace('T',' '))+'</div>')
                        if saved: st.caption('收藏保留原回答狀態；個人筆記可再補充核對。')
                        st.button('編輯小卡',key='edit_'+note['note_id'],on_click=open_note,args=(note,),width='stretch')
        with st.expander('匯出我的小知識'):
            st.download_button('下載JSON備份',json.dumps(notes.list(),ensure_ascii=False,indent=2),file_name='我的小知識.json',mime='application/json',key='export_notes')
    elif notes.list():
        st.info('沒有符合條件的小知識，試著換個關鍵字或篩選條件。')
    else:
        with st.container(border=True,key='note_intro'):
            html('<div class="empty-state"><img src="'+ICONS['knowledge']+'" alt=""><strong>從第一張小卡開始。</strong><p>點選「新增小知識」記下內容，<br>也可以在問答完成後，將回答收藏到這裡。</p></div>')
        html('<div class="mini-heading">可以這樣整理你的第一張小卡</div><div class="tips-grid"><div class="tip"><span>養殖管理</span><strong>一個清楚的標題</strong><p>用一句話描述想記住的重點，之後更好搜尋。</p></div><div class="tip"><span>魚種分類</span><strong>保留適用的對象</strong><p>把魚種與使用情境一起記下，不混用不同條件。</p></div><div class="tip"><span>觀察筆記</span><strong>記下當時的資料</strong><p>日期、觀察和量測單位，都是有用的紀錄。</p></div></div>')

else:
    heading('本次問答紀錄','回看問過的問題，把有用的回答收進小知識。','history')
    records = history()
    if records:
        indexed = {r['attempt_id']:r for r in reversed(records)}
        aid = st.selectbox('選擇問答紀錄',list(indexed),format_func=lambda key:indexed[key].get('at','')[:16].replace('T',' ')+' · '+record_details(indexed[key]).get('question',indexed[key]['question_id']))
        with st.container(border=True,key='answer_panel'): show_answer(indexed[aid])
    else:
        html('<div class="empty-state"><img src="'+ICONS['history']+'" alt=""><strong>新的發現，從一個問題開始。</strong><p>完成問答後，就能在這裡找回紀錄。</p></div>')
        st.button('開始第一個問答',on_click=navigate,args=('知識問答',),key='first_question')

html('<div class="page-footer"><span>Aquaculture Knowledge Platform · 養殖漁業知識平台</span><span>慢慢探索，日日有新知。</span></div>')
