"""Generate the cloud UI from the active presentation with no research inputs."""
import ast,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])
APP=ROOT/'research_staging/app_sessions/launch_20261118_154253'
text=(APP/'knowledge_platform.py').read_text(encoding='utf-8')
def change(old,new):
    global text
    assert old in text,old[:140]
    text=text.replace(old,new,1)
change('ROOT = SESSION.parents[2]\nsys.path[:0] = [str(SESSION), str(ROOT)]','sys.path.insert(0, str(SESSION))')
change('from answer_policy import FROZEN, engine\nfrom free_question_engine import question_info\nfrom knowledge_notes import KnowledgeNotes, TOPICS, SPECIES as NOTE_SPECIES',
    'from cloud_client import get_client, RemoteNotes as KnowledgeNotes, TOPICS, SPECIES as NOTE_SPECIES, gate, safe_answer_markdown')
change("MODELS = {'M1':'DeepSeek R1 · Qwen 7B', 'M2':'Qwen2.5 Coder · 7B', 'M3':'DeepSeek R1 · Llama 8B', 'M4':'Gemma 2 · 9B'}", "MODELS = {'M1':'M1 · DeepSeek R1 · Qwen 7B', 'M2':'M2 · Qwen2.5 Coder · 7B', 'M3':'M3 · DeepSeek R1 · Llama 8B', 'M4':'M4 · Gemma 2 · 9B'}")
start=text.index('@st.cache_resource(show_spinner=False)')
end=text.index('\ndef html(content):',start)
text=text[:start]+'''def load(corpus_version=None):
    return get_client()

@st.cache_data(show_spinner=False, ttl=30)
def load_content(corpus_version=None, workspace=None):
    return get_client().bootstrap()

@st.cache_data(ttl=1, show_spinner=False)
def history():
    return get_client().history()
''' + text[end:]
change(" or question_info(qid)", '')
change("try:\n    active = json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))", "gate()\n\ntry:\n    active = {'version':'remote-current-rag-v6','workspace':''}")
change("        model = st.selectbox('回答模型',list(MODELS),index=1,key='platform_model',format_func=lambda m:MODELS[m])", "")
change("    html('<div class=\"side-foot\">", "    model = st.session_state.get('platform_model','M2')\n    html('<div class=\"side-foot\">")
change("            mode = st.radio('提問方式'", "            model = st.selectbox('回答模型',list(MODELS),index=1,key='platform_model',format_func=lambda m:MODELS[m],help='預設使用M2。切換模型時可能需要等待載入；目前依序處理問答。')\n            mode = st.radio('提問方式'")
change('問題與推論於本機處理','四款模型與知識服務於本機運作')
change("page_title='臺灣水產養殖知識平台'", "page_title='Aquaculture Knowledge Platform'")
change("page_icon=str(SESSION/'assets/watercolor_chat.png')", "page_icon=str(SESSION/'assets/aquaculture_fish_favicon_v1.png')")
change("st.title('臺灣水產養殖知識平台')", "st.title('Aquaculture Knowledge Platform')")
change('<div class="brand-name">水產知識平台</div><div class="brand-sub">MARINE KNOWLEDGE</div>', '<div class="brand-name">Aquaculture<br>Knowledge Platform</div><div class="brand-sub">養殖漁業知識平台</div>')
change('MARINE KNOWLEDGE · 水產養殖知識平台', 'Aquaculture Knowledge Platform · 養殖漁業知識平台')
change("st.markdown(result.get('final_answer','本次未取得可顯示的回答。'))", "st.markdown(safe_answer_markdown(result.get('final_answer','本次未取得可顯示的回答。')),unsafe_allow_html=False)")
change("st.markdown('- '+str(item))", "st.markdown(safe_answer_markdown('- '+str(item)),unsafe_allow_html=False)")
old="""            for asset in c.get('media_assets',[])[:2]:
                if asset.get('path') and Path(asset['path']).is_file():
                    st.image(asset['path'],caption='引用原文 · 第'+str(asset.get('page',''))+'頁')"""
new="""            for asset in c.get('media_assets',[])[:2]:
                if asset.get('remote_asset_id'):
                    picture=get_client().image(asset['remote_asset_id'])
                    if picture: st.image(picture,caption='引用原文 · 第'+str(asset.get('page',''))+'頁')"""
change(old,new)
change("            for asset in c.get('media_assets',[])[:2]:", "            if source.get('attribution'): st.caption(str(source['attribution']))\n            for asset in c.get('media_assets',[])[:2]:")
ast.parse(text)
assert 'answer_policy' not in text and 'FROZEN' not in text and 'research_staging' not in text
assert 'C:\\my project' not in text and 'UnifiedQuestionRag' not in text
(WORK/'frontend/streamlit_app.py').write_text(text,encoding='utf-8')
(WORK/'frontend/requirements.txt').write_text('streamlit==1.67.0\nrequests==2.34.2\npillow==13.0.0\npyarrow==24.0.0\n',encoding='utf-8')
(WORK/'frontend/.streamlit/config.toml').write_text('[theme]\nbase = "light"\nprimaryColor = "#518BB1"\nbackgroundColor = "#F3FAFF"\nsecondaryBackgroundColor = "#F4FAFE"\ntextColor = "#24445A"\n\n[browser]\ngatherUsageStats = false\n',encoding='utf-8')
(WORK/'frontend/.streamlit/secrets.toml.example').write_text('RAG_BACKEND_DISCOVERY_URL = "https://raw.githubusercontent.com/ethanworkspace/hybrid-rag-aquaculture-knowledge-platform/refs/heads/codex/streamlit-cloud/streamlit_cloud/backend_endpoint.json"\nRAG_API_KEY = "SET_IN_STREAMLIT_SECRETS_ONLY"\nAPP_ACCESS_CODE = "SET_IN_STREAMLIT_SECRETS_ONLY"\n',encoding='utf-8')
(WORK/'frontend/.gitignore').write_text('.streamlit/secrets.toml\n__pycache__/\n*.sqlite3\n*.log\n.env\n',encoding='utf-8')
(WORK/'frontend/README.md').write_text('''# Aquaculture Knowledge Platform（養殖漁業知識平台）

這個目錄僅包含雲端介面、原創圖示與背景。網站可選M1–M4，預設M2；模型、RAG、來源原件與筆記儲存在私有本機服務。模型身分依本機核實登錄逐次檢查，未提供任意模型標籤存取。

Community Cloud入口：`streamlit_cloud/streamlit_app.py`。請在Secrets設定`RAG_BACKEND_DISCOVERY_URL`、`RAG_API_KEY`及`APP_ACCESS_CODE`，不要提交任何真正金鑰。部署使用Python 3.14。連線清單僅含公開後端網址，不能代替API金鑰；本機連線重啟時須更新該清單。

啟動命令：`streamlit run streamlit_app.py`。後端未設定或離線時會顯示連線狀態，不會生成示範答案。現階段為存取碼保護的單一研究工作區；持有同一存取碼的人共用雲端問答紀錄及小知識，並非多使用者隔離服務。
''',encoding='utf-8')
files=[]
credentials=json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
for path in sorted((WORK/'frontend').rglob('*')):
    if not path.is_file():continue
    data=path.read_bytes()
    for secret in credentials.values():assert secret.encode() not in data,path
    assert path.suffix.lower() not in ('.sqlite3','.pdf','.xlsx','.gguf','.safetensors')
    files.append({'path':path.relative_to(WORK/'frontend').as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
(WORK/'reports/frontend_publish_allowlist.json').write_text(json.dumps({'files':files,'private_inputs_included':False,'secret_scan_passed':True},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'frontend':str(WORK/'frontend'),'files':len(files),'secret_scan_passed':True}))
