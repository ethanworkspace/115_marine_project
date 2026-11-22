"""Professional platform presentation; existing corpus and answer policy unchanged."""
from pathlib import Path
from html import escape
from collections import Counter
import json
import sys
import base64
sys.dont_write_bytecode = True
SESSION = Path(__file__).resolve().parent
sys.path.insert(0, str(SESSION))
import streamlit as st
from answer_policy import SessionFairRag, FROZEN, VERSION, engine
from free_question_engine import question_info
from unified_question_engine import UnifiedQuestionRag
from src.unified_rag_v6.presentation import all_data_search,law_review,organized_source_catalog

st.set_page_config(page_title="臺灣水產養殖知識平台", page_icon="🌊", layout="wide", initial_sidebar_state="auto")
background_file = SESSION / "assets" / "ocean_watercolor_chibi_background.png"
background_uri = "data:image/png;base64," + base64.b64encode(background_file.read_bytes()).decode("ascii")
platform_styles = (SESSION / "platform.css").read_text(encoding="utf-8").replace("__OCEAN_BACKGROUND__", background_uri)
st.markdown("<style>" + platform_styles + "</style>", unsafe_allow_html=True)
MODELS = {"M1":"DeepSeek R1 · Qwen 7B", "M2":"Qwen2.5 Coder · 7B", "M3":"DeepSeek R1 · Llama 8B", "M4":"Gemma 2 · 9B"}
CATEGORIES = {"Fact":"養殖知識", "Water Quality":"水質環境", "Disease":"疾病防治", "Climate / Cold":"氣候防寒", "Medication / Law":"用藥法規", "Calculation":"養殖計算"}
SPECIES = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]

@st.cache_resource
def load(corpus_version=None):
    rt = UnifiedQuestionRag()
    rows = {r["question_id"]:r for r in engine.jl(FROZEN / "shared_contexts_180.jsonl")}
    sources = list(rt.unified.sources.values())
    return rt, rows, sources

@st.cache_data(ttl=1)
def history():
    path = SESSION / "generator_attempts.jsonl"
    if not path.is_file(): return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("result"): rows.append(row)
        except json.JSONDecodeError: continue
    return rows[-50:]

def html(text): st.markdown(text, unsafe_allow_html=True)
def official_url(source):
    return next((source.get(key) for key in ("dataset_url","resource_url","url") if isinstance(source.get(key),str) and source[key].startswith("https://")), None)
def section(title, note=""):
    html(f'<div class="section-label">{escape(title)}</div>' + (f'<div class="section-note">{escape(note)}</div>' if note else ""))
def reset_filters():
    st.session_state.update(platform_species="全部魚種", platform_topic="全部主題", platform_search="")

def details(record):
    return record.get("question_payload") or questions.get(record["question_id"]) or question_info(record["question_id"]) or {"question":record.get("question",record["question_id"]),"species":record.get("species",""),"top5":[]}

def show_sources(record):
    result = record["result"]
    cited = result.get("supporting_chunk_ids", [])
    free = bool(details(record).get("free_question")) or record["question_id"].startswith("FREE-")
    ids = list(dict.fromkeys(cited if free else (cited or record.get("evidence_decision", {}).get("supporting_chunk_ids", []))))
    contexts = {c["chunk_id"]:c for c in details(record).get("top5", [])}
    ids = [cid for cid in ids if cid in contexts]
    section("來源與支持", f"{len(ids)} 段引用原文" if cited else "本次可引用的資料")
    if not ids:
        html('<div class="empty-state"><span class="empty-glyph">≋</span><strong>目前沒有可引用的支持段落</strong><p>候選資料不等於答案依據。<br>可補充原始資料或查看回答中的查核方向。</p></div>')
    for number, cid in enumerate(ids, 1):
        c = contexts[cid]; source = source_map.get(c["source_id"], {})
        verified_quotes = [x["quote"] for x in result.get("validation_status",{}).get("exact_quote_checks",[]) if x["chunk_id"]==cid and x.get("quote_verified")]
        quote = "\n\n".join(verified_quotes) if free and verified_quotes else c["source_quote"]
        html(f'<div class="source-index">SOURCE {number:02d}</div><div class="source-title">{escape(source.get("title") or c["source_id"])}</div><div class="source-quote">{escape(quote)}</div>')
        for asset in c.get("media_assets", [])[:2]:
            if asset["kind"]=="TABLE":
                with st.expander("查看原始表格"):
                    st.dataframe(asset.get("metadata",{}).get("cells",[]),width="stretch",hide_index=True)
                    st.image(asset["path"],caption="原件表格影像 · 第"+str(asset.get("page"))+"頁")
            else:
                st.image(asset["path"],caption="引用原件圖像 · 第"+str(asset.get("page"))+"頁")
        with st.expander("版本與原文位置"):
            st.caption("來源版本：" + c["source_version"])
            st.caption("原文位置：" + c["exact_locator"])
            st.caption("原始紀錄：" + c.get("source_record_id", "未記載"))
            if source.get("attribution"): st.caption(source["attribution"])
            url = official_url(source)
            if isinstance(url,str) and url.startswith("https://"): st.link_button("查看官方來源", url, key="citation_link_"+cid)

def show_answer(record):
    out = record["result"]; origin = out["answer_origin"]
    text, style = {"ANSWERED_GROUNDED":("來源支持",""),"ANSWERED_PARTIAL":("部分資訊","partial"),"INSUFFICIENT_EVIDENCE":("查核指引","guide"),"VALIDATION_FAILED":("待核對","guide")}[out["answer_status"]]
    html(f'<div class="answer-head"><span class="answer-title">專業解答</span><span class="badge {style}">{text}</span></div>')
    if record["question_id"].startswith("FREE-"): st.caption("問題："+details(record)["question"])
    if record.get("api_error"): st.warning("本次模型連線未完成，以下內容包含系統提供的查核說明。")
    st.markdown(out["final_answer"])
    labels = {"MODEL_GENERATED":"模型直接生成","DETERMINISTIC_EVIDENCE_EXTRACTION":"來源內容摘取","SYSTEM_GUIDANCE":"系統查核說明","ABSTAINED":"資訊缺口說明","VALIDATION_FAILED":"輸出待核對"}
    html(f'<div class="answer-meta">{escape(MODELS.get(record["model_id"],record["model_id"]))}　·　{escape(labels.get(origin,origin))}</div>')
    if out.get("missing_information"):
        with st.expander("尚需補充的資訊"):
            for item in out["missing_information"]: st.markdown("- "+str(item))
    question = details(record).get("question",record.get("question",""))
    export = "# 水產養殖知識問答\n\n## 問題\n"+question+"\n\n## 回答\n"+out["final_answer"]+"\n\n回答來源："+labels.get(origin,origin)+"\n模型："+MODELS.get(record["model_id"],record["model_id"])+"\n"
    st.download_button("下載本次回答",export,file_name=record["question_id"]+"_answer.md",mime="text/markdown",key="download_answer")

def advanced(record=None):
    with st.expander("進階資訊"):
        st.caption("Corpus SHA-256："+runtime.runtime.db_sha256)
        st.caption("作答策略版本："+(record.get("prompt_version",VERSION) if record else VERSION))
        if record:
            st.caption("Question ID："+record["question_id"])
            st.caption("Model digest："+record.get("model_digest","未記錄"))
            st.caption("Context digest："+record.get("context_digest","未記錄"))
            st.code(record.get("raw_model_response",""),language="json")
            st.json(record["result"]["validation_status"])
        else: st.caption("產生回答後，可在此查閱原始輸出與驗證紀錄。")

try:
    runtime, questions, sources = load(json.loads((Path(r'C:\my project\115_marine_project')/'research_staging/unified_rag_active.json').read_text(encoding='utf-8'))['version'])
except Exception as exc:
    st.title("臺灣水產養殖知識平台")
    st.error("服務暫時無法載入，請確認Ollama與本機知識庫是否可用。")
    with st.expander("連線詳細資訊"): st.code(str(exc))
    st.stop()
source_map = {s["source_id"]:s for s in sources}
species_counts = Counter(r["species"] for r in questions.values())

with st.sidebar:
    html('<div class="brand"><div class="brand-mark">≋</div><div><div class="brand-name">MARINE KNOWLEDGE</div><div class="brand-sub">臺灣水產養殖知識平台</div></div></div>')
    html('<div class="sidebar-label">WORKSPACE</div>')
    page = st.radio("功能導覽",["知識問答","來源資料","資料管理","法規核對","本次紀錄"],label_visibility="collapsed",key="platform_page")
    st.divider(); html('<div class="sidebar-label">查詢設定</div>')
    species = st.selectbox("養殖魚種",["全部魚種"]+[s for s in SPECIES if s in species_counts],key="platform_species",format_func=lambda s:"自動辨識 / 全部魚種" if s=="全部魚種" else s)
    model = st.selectbox("回答模型",list(MODELS),index=1,format_func=lambda m:MODELS[m],key="platform_model")
    html(f'<div class="model-note"><strong>{model} · 本機模型</strong><br>依來源內容回答，保留原文引用與資料缺口。</div>')
    st.divider()
    with st.expander("知識庫概覽"):
        a,b = st.columns(2); a.metric("登錄來源",len(sources)); b.metric("問答候選段落",f"{len(runtime.runtime.rows):,}")
        st.caption("已整理原件："+str(runtime.unified.manifest["counts"]["documents"])+"份；文字、表格及圖片分別保留來源位置。")
        st.caption("各來源依其原始魚種、版本與使用範圍提供資訊。")
    st.button("重設篩選",on_click=reset_filters,width="stretch",key="reset_filters")
    html('<div class="side-foot">LOCAL KNOWLEDGE WORKSPACE<br>問題與模型推論於本機處理</div>')

html(f'<div class="breadcrumb">知識工作台　/　<b>{page}</b></div>')
if page=="知識問答":
    html('<div class="hero"><div><div class="eyebrow">AQUACULTURE KNOWLEDGE PLATFORM</div><h1>養殖問題，從可靠來源開始。</h1><p>依魚種與主題探索養殖知識，取得清楚的回答，<br>並隨時回查支持內容與原始資料。</p></div><div class="hero-art" aria-hidden="true"><span class="wave">≋</span><small>MARINE / KNOWLEDGE</small></div></div>')
else:
    section({"來源資料":"來源資料庫","資料管理":"文件與多媒體資料","法規核對":"官方法規版本核對","本次紀錄":"本次問答紀錄"}[page],"查看實際使用的資料與來源範圍。" if page=="來源資料" else "查看清洗、切分及索引狀態，回查原始表格與圖片。" if page=="資料管理" else "核對官方版本、條文與原始附件，保留本機舊版差異。" if page=="法規核對" else "查閱這次啟動期間留下的回答與來源紀錄。")
html('<div class="stats">'+''.join(f'<div class="stat"><div><div class="stat-label">{label}</div><div class="stat-value">{number}<span class="stat-unit">{unit}</span></div></div><span class="stat-sign">{sign}</span></div>' for label,number,unit,sign in [("題庫問題",len(questions),"題","▤"),("養殖魚種",len(species_counts),"類","≈"),("可選模型",len(MODELS),"款","◇")])+'</div>')

if page=="知識問答":
    left,right = st.columns([2.05,1],gap="large"); record=None
    with left:
        with st.container(border=True,key="query_panel"):
            section("你想了解什麼？","直接輸入養殖問題，或切換至既有題庫。")
            mode = st.radio("提問方式",["自由提問","題庫問答"],horizontal=True,key="platform_question_mode")
            if mode=="自由提問":
                text = st.text_area("輸入你的問題",placeholder="例如：虱目魚寒流來時，魚塭有哪些操作應避免？",height=135,max_chars=2000,key="platform_free_question")
                st.caption("魚種未指定時會依問題辨識；若無法辨識，只查詢通用養殖資料。")
                if runtime.runtime.reranker is None: st.caption("首次自由提問需初始化本機檢索服務，可能較久。")
                if st.button("送出問題",key="free_answer",type="primary",width="stretch",disabled=not text.strip()):
                    try:
                        with st.spinner("正在檢索知識庫、重排序並產生回答…"): st.session_state["last"]=runtime.call_free(text,model,selected_species=species)
                        history.clear()
                    except Exception as exc:
                        st.error("本次問答未完成，請確認問題內容、Ollama與檢索服務狀態後再試。")
                        with st.expander("連線詳細資訊"): st.code(str(exc))
                last=st.session_state.get("last")
                if last and last["question_id"].startswith("FREE-") and last["model_id"]==model: record=last
            else:
                cats = [c for c in CATEGORIES if any(r.get("category")==c for r in questions.values())]
                topic = st.pills("問題主題",["全部主題"]+cats,default="全部主題",format_func=lambda c:CATEGORIES.get(c,c),key="platform_topic",wrap=True)
                search = st.text_input("搜尋題目",placeholder="例如：水溫、投餌、放養密度…",key="platform_search")
                filtered = [q for q,r in questions.items() if (species=="全部魚種" or r["species"]==species) and (not topic or topic=="全部主題" or r.get("category")==topic) and (not search.strip() or search.strip().casefold() in r["question"].casefold())]
                if filtered:
                    if st.session_state.get("platform_question") not in filtered: st.session_state["platform_question"]=filtered[0]
                    qid = st.selectbox(f"選擇問題 · {len(filtered)} 題",filtered,format_func=lambda q:questions[q]["question"],key="platform_question")
                    selected=questions[qid]
                    html(f'<div class="question-preview"><span class="chip">{escape(selected["species"])}</span><span class="chip chip-muted">{escape(CATEGORIES.get(selected.get("category"),selected.get("category","其他")))}</span><p>{escape(selected["question"])}</p></div>')
                    if st.button("查詢專業解答",key="answer",type="primary",width="stretch"):
                        try:
                            with st.spinner("正在讀取來源並產生回答…"): st.session_state["last"]=runtime.call(selected,model,stage="INTERACTIVE_KNOWLEDGE_PLATFORM")
                            history.clear()
                        except Exception as exc:
                            st.error("本次模型呼叫未完成，請確認Ollama及模型狀態後再試。")
                            with st.expander("連線詳細資訊"): st.code(str(exc))
                    last=st.session_state.get("last")
                    if last and last["question_id"]==qid and last["model_id"]==model: record=last
                else: st.info("沒有符合篩選條件的題目，請調整關鍵字或魚種。")
        with st.container(border=True,key="answer_panel"):
            if record: show_answer(record)
            else: html('<div class="empty-state"><span class="empty-glyph">≋</span><strong>讓來源成為回答的依據</strong><p>輸入問題並送出，或從題庫挑選問題。<br>回答、資訊缺口與對應來源會顯示在這裡。</p></div>')
        advanced(record)
    with right:
        with st.container(border=True,key="source_panel"):
            if record: show_sources(record)
            else:
                section("來源與支持","原文與回答並列，查核更直接。")
                html('<div class="empty-state"><span class="empty-glyph">▤</span><strong>回答的來源，一目了然</strong><p>產生回答後，可在此查閱<br>引用原文、資料版本與定位。</p></div>')
        with st.container(border=True,key="guide_panel"):
            section("查詢小指南")
            for number,title,text in [("01","先確認魚種","不同品種與養殖情境，適用資訊可能不同。"),("02","查看回答範圍","區分來源支持的內容，以及尚需補齊的資訊。"),("03","回查原始資料","重要數值、條件與用藥資訊，應核對原文與適用版本。")]: html(f'<div class="guide-step"><span class="guide-number">{number}</span><div><strong>{title}</strong><p>{text}</p></div></div>')
elif page=="來源資料":
    columns=st.columns(2,gap="large")
    for i,source in enumerate(sources):
        with columns[i%2]:
            with st.container(border=True):
                section(source.get("title",source["source_id"]),source.get("publisher") or "發布機關未另記載")
                limited = source.get("license","").startswith("NO_FULLTEXT_LICENSE_CLAIMED")
                if source.get("license"): st.caption("資料形式：有限原創事實摘要" if limited else "使用依據："+str(source["license"]))
                if limited: st.markdown("依可定位的原始出版內容整理事實摘要，原件全文未納入索引。")
                elif source.get("attribution"): st.markdown(source["attribution"])
                url=official_url(source)
                if isinstance(url,str) and url.startswith("https://"): st.link_button("查看官方資料",url,key="source_link_"+str(i))
                with st.expander("適用範圍與版本紀錄"):
                    if limited and source.get("attribution"): st.caption(source["attribution"])
                    for name,key in [("使用範圍","processing_scope"),("版本核驗","version_status"),("適用性","applicability_status"),("完整性","completeness_status")]:
                        if source.get(key): st.write(name+"："+str(source[key]))
                    st.caption("Source ID："+source["source_id"]); st.caption("SHA-256："+source["source_sha256"])
elif page=="法規核對":
    law_review(runtime)
elif page=="資料管理":
    summary=runtime.unified.manifest["counts"]
    a,b,c,d=st.columns(4)
    a.metric("不同原件",summary["documents"])
    b.metric("解析頁數",f'{summary["document_pages"]:,}')
    c.metric("原始表格",summary["element_kinds"].get("TABLE",0))
    d.metric("圖片向量",summary["image_embeddings"])
    st.caption("所有原件已入庫並建立文字或影像向量。問答仍檢查魚種、數值、版本與解析品質；掃描或表格待核對內容可在全部資料搜尋中回查。")
    extra_a,extra_b=st.columns(2)
    extra_a.metric("全文索引片段",f'{summary["archive_units"]:,}')
    extra_b.metric("去重文字向量",f'{summary["distinct_text_vectors_used"]:,}')
    organized_source_catalog(runtime)
    all_data_search(runtime)
    labels={"USER_ATTESTED_LOCAL_RESEARCH_FULLTEXT":"依本輪使用聲明供本機研究使用","OFFICIAL_STATUTORY_SNAPSHOT_ART9":"已保存官方條文／附件快照","EXISTING_ADMITTED_STRUCTURED_RECORD_SCOPE":"依原核准欄位使用","PRIOR_APPROVED_NATIVE_FIELDS_SCOPE_ONLY":"沿用既有准入，僅限原始欄位","OGL_V1_EXACT_OFFICIAL_RESOURCE_EXCEPTION_SCREENED":"官方開放資源，保留例外限制","STATUTORY_TEXT_ART9_HISTORICAL_SNAPSHOT":"法規歷史原文，須核對版本","EXPLICIT_RESTRICTION_FULLTEXT_QUARANTINED":"使用條件有保留，全文准入待核","FULLTEXT_USAGE_BASIS_UNVERIFIED":"全文使用依據待確認"}
    overview=runtime.document_overview()
    st.dataframe([{"文件":r["title"],"格式":r["original_format"],"處理":"已解析" if r["parse_status"]=="PARSED" else r["parse_status"],"使用範圍":labels.get(r["rights_status"],r["rights_status"]),"文字／圖表元素":r["elements"],"結構化原始紀錄":r["records"],"可檢索段落":r["retrieval_chunks"]} for r in overview],width="stretch",hide_index=True)
    chosen=st.selectbox("查看文件內容",[r["document_id"] for r in overview],format_func=lambda did:next(r["title"] for r in overview if r["document_id"]==did),key="library_document")
    with runtime.unified.connect() as con:
        doc=dict(con.execute("SELECT * FROM documents WHERE document_id=?",(chosen,)).fetchone())
        tables=[dict(r) for r in con.execute("SELECT * FROM document_elements WHERE document_id=? AND kind='TABLE' LIMIT 20",(chosen,))]
        images=[dict(r) for r in con.execute("SELECT e.*,a.path FROM document_elements e JOIN media_assets a USING(asset_id) WHERE e.document_id=? AND e.kind IN ('IMAGE','PAGE_RENDER','LEGACY_IMAGE') AND a.width>=70 AND a.height>=35 LIMIT 12",(chosen,))]
        records=[dict(r) for r in con.execute("SELECT field_locator,record_json FROM structured_records WHERE document_id=? LIMIT 5",(chosen,))]
    st.caption(labels.get(doc["rights_status"],doc["rights_status"]))
    tabs=st.tabs(["表格","圖片","原始紀錄"])
    with tabs[0]:
        st.caption("預覽前20個可辨識表格；完整擷取結果與原件均保存在資料庫。空白與合併儲存格未補成0。")
        if not tables: st.info("這份文件未擷取到可辨識的表格結構；掃描或複雜表格仍保留在原件中。")
        for i,table in enumerate(tables):
            with st.expander("第"+str(table["page"])+"頁 · 表格"+str(i+1)):
                st.dataframe(json.loads(table["metadata_json"])["cells"],width="stretch",hide_index=True)
    with tabs[1]:
        st.caption("預覽前12張圖片或原頁影像；整頁影像也保留向量圖、圖表與版面，原始文件不變。")
        if not images: st.info("這份文件沒有符合顯示條件的內嵌圖片。")
        cols=st.columns(3)
        for i,image in enumerate(images):
            with cols[i%3]:
                st.image(image["path"],caption="原件第"+str(image["page"])+"頁")
                caption=json.loads(image["metadata_json"]).get("caption")
                if caption: st.caption(caption)
        st.caption("圖片與 OCR 可供回查；未核驗的圖說、數值或疾病判讀不會直接成為專業答案依據。")
    with tabs[2]:
        if records:
            st.caption("以下預覽前5筆原始紀錄，完整資料均已保存。")
            for item in records:
                with st.expander(item["field_locator"]): st.json(json.loads(item["record_json"]))
        else: st.caption("此文件以頁面、文字區塊及圖表位置保存。")
        with st.expander("原件與版本紀錄"):
            st.caption("SHA-256："+doc["sha256"])
            st.caption("文件識別："+doc["document_id"])
            st.caption("版本："+str(doc["source_version"]))
else:
    records=history()
    if records:
        indexed={r["attempt_id"]:r for r in reversed(records)}
        aid=st.selectbox("選擇紀錄",list(indexed),format_func=lambda key:indexed[key].get("at","")[:16].replace("T"," ")+" · "+MODELS.get(indexed[key]["model_id"],indexed[key]["model_id"])+" · "+details(indexed[key]).get("question",indexed[key]["question_id"]))
        record=indexed[aid]; selected=details(record)
        st.caption(selected.get("species","")+" · "+selected.get("question",record["question_id"]))
        left,right=st.columns([2.05,1],gap="large")
        with left:
            with st.container(border=True,key="answer_panel"): show_answer(record)
            advanced(record)
        with right:
            with st.container(border=True,key="source_panel"): show_sources(record)
    else: html('<div class="empty-state"><span class="empty-glyph">▤</span><strong>尚未留下問答紀錄</strong><p>從「知識問答」提出第一個問題後，即可在此回查。</p></div>')
html('<div class="page-footer"><span>MARINE KNOWLEDGE · 水產養殖知識平台</span><span>依來源理解問題，保留查核脈絡。</span></div>')
