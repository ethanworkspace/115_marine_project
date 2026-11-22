from pathlib import Path
import json,sys,collections,statistics,datetime,re
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
W=Path(__file__).resolve().parent;I=W.parent/'fish_test_corpus_v3_frozen_run_20261021_133102'
d=json.loads((W/'recomputed_data_package.json').read_text(encoding='utf-8'));M=['M1','M2','M3','M4'];keys=list(d['formulas'])[:-1]
def fmt(x,n=4):return 'N/A' if x is None else f'{x:.{n}f}'
def pct(x):return 'N/A' if x is None else f'{100*x:.2f}%'
def ratio(x):return f"{x['correct']}/{x['n']} ({pct(x['accuracy'])})" if x['n'] else 'N/A (N=0)'
def wr(n,v):(W/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jl(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
metrics=[]
for l in ['model','system']:
 for m in M:
  for k,s in d['allstats'][l][m].items():
   p=d['paired'][l][k];metrics.append([l,m,k,s['mean'],s['n'],s['median'],s['sd'],s['min'],s['max'],p['n'],p['models'][m]['mean']])
pquestions=[[p['metric'],p['question_id'],p['species'],p['original_question'],*[p['models'][m]['correct'] for m in M],' | '.join(p['source_group_ids'])] for p in d['pairs']]
preasons=[[p['metric'],p['question_id'],p['species'],m,p['models'][m]['verdict'],p['models'][m]['reason'],p['models'][m]['observable_raw_answer'],p['reference_answer'],p['rubric_sha256'],' | '.join(p['source_group_ids']),p['models'][m]['parsed_numeric_value'],p['models'][m]['reference_numeric_value']] for p in d['pairs'] for m in M]
psummary=[]
for typ in ['Logical','Arithmetic']:
 for m in M:
  x=next(x for x in d['paired_summary'] if x['metric']==typ and x['model_id']==m and x['view']=='all_available')['stats'];psummary.append([typ,m,None,None,None,None,x['correct'],x['n'],x['accuracy'],x['not_evaluable']])
flow=[[r['model_id'],r['raw_quality_valid_n'],r['raw_citation_pass_among_judge_valid'],r['final_model_generated'],r['deterministic_extraction'],r['system_abstained'],r['validation_failed'],r['raw_model_declared_abstention'],r['system_quality_valid_n'],r['system_content_nonanswers']] for r in d['flows']]
species=[]
for typ in ['Logical','Arithmetic']:
 for sp in sorted({x['species'] for x in d['coverage']}):
  for m in M:
   x=next(x for x in d['paired_species'] if x['metric']==typ and x['species']==sp and x['model_id']==m);species.append([typ,sp,m,x['n'],x['correct'],x['incorrect'],x['accuracy']])
for sp,ls in d['breakdown']['species'].items():
 for m in M:
  for k in ['faithfulness','judge_answer_relevance','bge_m3_cosine','logical_accuracy','arithmetic_accuracy']:
   s=ls['model'][m][k];species.append(['All Available '+k,sp,m,s['n'],None,None,s['mean']])
glabels={g:f'G{i+1:02d}' for i,g in enumerate(sorted(d['source_dependency']['group_memberships']))}
fLabels={g:f'F{i+1:02d}' for i,g in enumerate(sorted(d['source_dependency']['file_memberships']))}
groupRows=[]
for g in d['source_groups']+d['source_files']:
 a,b,c=g['within_group'],g['without_group'],g['all_eligible'];groupRows.append([glabels.get(g['source_group'],fLabels.get(g['source_group'])),g['source_type'],g['source_group'],g['source_question_n'],g['source_question_share'],g['metric'],g['answer_layer'],g['model_id'],a['correct'],a['n'],a['accuracy'],b['n'],b['accuracy'],c['accuracy'],g['all_minus_without_accuracy']])
special=[]
def excerpt(value):
 text=re.sub(r'\s+',' ',str(value));return text if len(text)<=500 else text[:500]+'… [完整原文見 incomplete_and_echo_cases_preserved_5.jsonl]'
for x in d['special_cases']:
 for l,v in x['per_layer'].items():
  special.append([x['model_id'],x['question_id'],l,x['question'],excerpt(x['raw_model_response']),excerpt(json.dumps(x['final_response'],ensure_ascii=False)),v['content']['content_status'],v['bge_before']['cosine'],v['bge_after']['cosine'],(v['logical_before'] or {}).get('verdict'),(v['logical_after'] or {}).get('verdict'),(v['arithmetic_before'] or {}).get('verdict'),(v['arithmetic_after'] or {}).get('verdict')])
methods=[[k,v] for k,v in d['formulas'].items()]
methods+=[['Input run',str(I)],['Frozen reference status','AUTO_SOURCE_VERIFIED; NOT_HUMAN_GOLD'],['No new models run','0 generator calls; no Judge/Embedding rescoring'],['Raw vs system','System layer shares the same generator timing/IFR; not a second independent measurement'],['Recompute script',str(W/'recompute_final_audit.py')]]
for m,s in d['models'].items():methods.extend([[m+' actual tag',s['tag']],[m+' digest',s['digest']],[m+' quantization',s['details']['quantization_level']]])
methods.extend([['GPU and saved execution environment',json.dumps(d['hardware'],ensure_ascii=False)],['Corpus version',d['corpus']['corpus_version']],['Corpus SHA256',d['corpus']['database_sha256']],['Generator settings',json.dumps(d['generation_options'],ensure_ascii=False)]])
wr('final_workbook_data.json',{'metrics':metrics,'paired_summary':psummary,'paired_questions':pquestions,'paired_reasons':preasons,'species':species,'groups':groupRows,'flow':flow,'cross':[[r['model_id'],r['final_answer_origin'],r['judge_valid_raw_n'],r['raw_citation_fail_n'],r['insufficient_evidence_state_n']] for r in d['judge_cross']],'special':special,'methods':methods,'audit':d['audit'],'coverage':[[x['species'],x['question_n'],x['full_support_n'],x['logical_qualified_n'],x['arithmetic_qualified_n'],x['any_context_n'],x['full_top5_n']] for x in d['coverage']]})

# A thesis chapter uses plain black headings, readable CJK type and restrained tables.
doc=Document();sec=doc.sections[0];sec.page_width=Cm(21);sec.page_height=Cm(29.7);sec.top_margin=Cm(2);sec.bottom_margin=Cm(2);sec.left_margin=Cm(2.2);sec.right_margin=Cm(2.2)
for sn in ['Normal','Title','Subtitle','Heading 1','Heading 2','Caption']:
 s=doc.styles[sn];s.font.name='Microsoft JhengHei';s._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft JhengHei');s.font.color.rgb=RGBColor(0,0,0)
doc.styles['Normal'].font.size=Pt(10.5);doc.styles['Normal'].paragraph_format.line_spacing=1.25;doc.styles['Normal'].paragraph_format.space_after=Pt(6)
doc.styles['Title'].font.size=Pt(22);doc.styles['Heading 1'].font.size=Pt(15);doc.styles['Heading 2'].font.size=Pt(12)
for sn in ['Heading 1','Heading 2']:doc.styles[sn].paragraph_format.space_before=Pt(9);doc.styles[sn].paragraph_format.space_after=Pt(6)
footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
r=footer.add_run();field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');r._r.addnext(field)
tables=[]
def p(t):doc.add_paragraph(t)
def h(t,page=False):
 if page:doc.add_page_break()
 doc.add_heading(t,level=1)
def table(caption,headers,rows,widths,source,size=9):
 cap=doc.add_paragraph(caption,style='Caption');cap.paragraph_format.keep_with_next=True
 t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
 for c,w in zip(t.columns,widths):c.width=Cm(w)
 for i,txt in enumerate(headers):t.rows[0].cells[i].text=str(txt)
 for row in rows:
  cells=t.add_row().cells
  for i,v in enumerate(row):cells[i].text=str(v if v is not None else 'N/A')
 for ri,row in enumerate(t.rows):
  pr=row._tr.get_or_add_trPr();no=OxmlElement('w:cantSplit');pr.append(no)
  if ri==0:repeat=OxmlElement('w:tblHeader');pr.append(repeat)
  for ci,cell in enumerate(row.cells):
   cell.width=Cm(widths[ci]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER;tc=cell._tc.get_or_add_tcPr()
   borders=OxmlElement('w:tcBorders')
   for edge in ['top','left','bottom','right']:
    q=OxmlElement('w:'+edge);q.set(qn('w:val'),'single');q.set(qn('w:sz'),'4');q.set(qn('w:color'),'D9D9D9');borders.append(q)
   tc.append(borders);marg=OxmlElement('w:tcMar')
   for edge in ['top','left','bottom','right']:
    q=OxmlElement('w:'+edge);q.set(qn('w:w'),'65');q.set(qn('w:type'),'dxa');marg.append(q)
   tc.append(marg)
   shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E7EEF4' if ri==0 else ('F6F8FA' if ri%2 else 'FFFFFF'));tc.append(shade)
   for par in cell.paragraphs:
    par.paragraph_format.line_spacing=1.1;par.paragraph_format.space_after=Pt(2);par.paragraph_format.space_before=Pt(2)
    par.alignment=WD_ALIGN_PARAGRAPH.LEFT if ci==0 else WD_ALIGN_PARAGRAPH.CENTER
    for run in par.runs:run.font.size=Pt(size);run.bold=ri==0
 doc.add_paragraph('資料來源：'+source+'。',style='Caption')
 tables.append({'caption':caption,'headers':headers,'rows':rows,'source':source})

doc.add_paragraph('Corpus v3 凍結評測研究結果',style='Title')
doc.add_paragraph('第四章 結果與討論',style='Subtitle')
p('本研究完成單一隔離 Hybrid-RAG 系統的凍結回歸評測。六魚種共180筆題目分別由四款本地模型生成，共保存720筆唯一最終紀錄及720筆原始嘗試。結果提供可追溯的系統效能與回答行為量測；專業品質僅限具來源支持的子集，不能據此推論全部水產養殖問題的正確率。')
h('一 研究環境與模型設定')
p('實際執行環境使用 NVIDIA GeForce RTX 4060，記錄的顯示記憶體為8188 MiB，驅動版本610.88，Ollama版本0.40.5。四款Generator依序載入、暖機及卸載，Judge評分與Generator效能量測分開。模型身分依保存的Ollama內容digest與metadata核對；本次核對沒有重新雜湊完整模型權重bytes。')
names={'M1':'DeepSeek R1 Distill Qwen 7B','M2':'Qwen2.5 Coder 7B Instruct','M3':'DeepSeek R1 Distill Llama 8B','M4':'Gemma2 9B It'}
table('表4之1 四款模型的凍結設定',['模型','身分','架構','量化'],[[m,names[m],d['models'][m]['details']['family'],d['models'][m]['details']['quantization_level']] for m in M],[1.1,9,2.7,3.8],'frozen_evaluation_manifest.json 與保存的模型metadata')
p('M3使用已核實的Llama 8B GGUF，未以其他架構的deepseek-r1:8b代替。共同生成參數為temperature=0、top_p=1、seed=21021、num_predict=1536及num_ctx=8192。各模型的完整標籤與digest另存最終統計核對表及重現性Manifest。')
c=d['corpus']['counts'];p(f"指定Corpus版本為{d['corpus']['corpus_version']}，包含{c['sources']}筆來源登錄、{c['unique_raw_sha256']}份不同原始SHA、{c['chunks']:,}個Chunk，其中{c['retrieval_eligible_chunks']:,}個可檢索、{c['context_only_chunks']}個僅供背景。檢索整合SQLite FTS5 BM25、BGE-M3 1024維Dense、RRF k=60及BGE Reranker v2-m3，並依凍結規則執行來源與魚種適用性檢查。")
p('來源核准、開放授權、身分與版本核驗及證據適用性分開保存。DGBAS僅限2020年單年度描述性Fact；無年度鰻魚統計不補造年度；藥品許可資訊不等於現行劑量或停藥建議。')

h('二 題庫與證據資格',True)
p('原題庫來自六份工作簿，每魚種30筆。本次逐題核對題目庫工作表的原始列號、題號、問題全文與工作簿SHA，未重複匯入同工作簿的測試資料表。180筆紀錄含175種不同題幹；歷史資料另標示15對疑似近似題。所有原始紀錄均保留，去重僅作敏感度分析。')
table('表4之2 六魚種的來源支持與檢索範圍',['魚種','題數','完整支持','Logical資格','算術資格','有Context','完整Top5'],[[x['species'],x['question_n'],x['full_support_n'],x['logical_qualified_n'],x['arithmetic_qualified_n'],x['any_context_n'],x['full_top5_n']] for x in d['coverage']],[2.4,1.7,2.4,2.7,2.3,2.4,2.7],'180筆凍結Question Context及來源核驗參考答案',8.5)
p('完整來源支持共50題，其中37題具Logical Rubric，13題具來源綁定的應用算術判準。其餘130題包括17題部分支持、17題適用範圍未核實、84題本版未找到完整答案及12題問題條件不足。未找到本版證據不代表外部世界不存在答案，也不自動構成正確拒答真值。')
p('本版174題至少有一筆Context、124題具完整Top-5，共751段最終Context。50題中49題檢索命中來源支持，FT-grouper-Q16保留為來源存在而Top-5漏失。此題未被改列為來源不存在。原180題已反覆參與系統改善，本次屬回歸及探索性比較，並非全新未曝光Holdout。')
p('所有50題均為AUTO_SOURCE_VERIFIED，Human Gold為0。評測先凍結來源、原文Span、參考答案與Rubric，再執行生成。Logical與Arithmetic準確率的分母只包括具判準且實際可判定的回答；拒答、純題目複誦或無可辨識結果維持N/A，另以回答涵蓋率呈現。')

h('三 原始模型的十一項指標',True)
labels={'faithfulness':'Faithfulness','judge_answer_relevance':'Judge Relevance','bge_m3_cosine':'BGE-M3 cosine','structured_ifr':'Structured IFR','ttft_seconds':'TTFT 秒','tps':'TPS','peak_system_ram_gib':'RAM峰值平均 GiB','peak_dedicated_vram_gib':'VRAM峰值平均 GiB','logical_accuracy':'Logical Accuracy','arithmetic_accuracy':'Arithmetic Accuracy'}
rows=[]
for k in keys:
 cells=[]
 for m in M:
  s=d['allstats']['model'][m][k];v=pct(s['mean']) if k in ['structured_ifr','logical_accuracy','arithmetic_accuracy'] else fmt(s['mean'],3 if k in ['ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib'] else 4);cells.append(f"{v}\nN={s['n']}")
 rows.append([labels[k],*cells])
table('表4之3 原始模型指標及各自有效樣本數',['指標',*M],rows,[5,2.9,2.9,2.9,2.9],'保存的Judge BGE Generator串流及準確率JSONL重新彙總',8.5)
p('第十一項為共用檢索Context Precision@5，按Relevant段落數除以5計算。12題60段既有探索性子集的平均為0.30；每魚種2題，吳郭魚、烏魚、虱目魚與鱸魚均0.20，石斑魚0.40，鰻魚0.60。這不是180題整體P@5，303段UNVERIFIED保持未驗證，未以低文字重疊補標為Irrelevant。')
p('表中RAM與VRAM為每次呼叫系統層級採樣峰值的平均，每0.5秒採樣，並非模型程序專屬記憶體。TTFT從串流呼叫包裝器啟動至首個可見JSON內容，包含取樣器初始化成本；不代表首個有意義答案字詞的延遲。TPS採Ollama eval_count除以eval_duration秒數，可能包含引擎計入的推理token。')

h('四 相同題目的配對比較',True)
p('All Available分析使用每模型各自可評估回答，樣本集合不同。配對分析則固定Question ID，只保留四模型皆有有效分數的27題Logical與7題Arithmetic。兩種分析分開呈現，未把不同分母的平均值直接視為嚴格公平差異。')
rows=[]
for typ in ['Logical','Arithmetic']:
 sub=[x for x in d['paired_summary'] if x['metric']==typ and x['view']=='four_model_common'];rows.append([typ,*[ratio(next(x for x in sub if x['model_id']==m)['stats']) for m in M]])
table('表4之4 四模型共同有效題目',['指標',*M],rows,[3.4,3.3,3.3,3.3,3.3],'paired_question_comparison_34.jsonl 相同Question ID',9)
p('在此27題Logical子集中，M4為26題正確，M3為25題，M2為24題，M1為21題；7題Arithmetic子集中，M1為6題正確，M2與M4各5題，M3為2題。這些數字描述固定小型子集，不是整體顯著性差異。每一題的四模型原始回答、判定原因、原文Span與Rubric SHA均保存在配對分析資料。')
for typ in ['Logical','Arithmetic']:
 rows=[]
 for sp in sorted({x['species'] for x in d['coverage']}):
  sub=[x for x in d['paired_species'] if x['metric']==typ and x['species']==sp];rows.append([sp,*[(f"{x['correct']}/{x['n']}" if x['n'] else 'N/A') for m in M for x in sub if x['model_id']==m]])
 table('表4之'+('5' if typ=='Logical' else '6')+' '+typ+'共同題目的魚種分布',['魚種',*M],rows,[3.4,3.3,3.3,3.3,3.3],'paired_analysis.json species_distribution',8.5)
p('Arithmetic共同子集未涵蓋石斑魚；其他魚種也僅1至2題。未進行假設檢定或以此選出正式Winner。成對比較的雙方同時正確、同時錯誤及單方正確筆數另列於統計核對表。')

h('五 來源依賴與組成敏感度',True)
dep=d['source_dependency'];p(f"50題只對應{dep['source_group_n']}組原始紀錄或PDF頁，並共享{dep['source_file_n']}份原件。最大單一群組包含{max(len(v) for v in dep['group_memberships'].values())}題，占50題的{pct(dep['max_group_question_share'])}。同一頁衍生多題或多魚種通用題，不能當成多份互相獨立的專家知識。")
rows=[]
for g,qids in sorted(dep['group_memberships'].items()):
 l=next(x for x in d['source_groups'] if x['source_group']==g and x['metric']=='Logical' and x['answer_layer']=='model' and x['model_id']=='M1')['within_group']['eligible_n'];a=next(x for x in d['source_groups'] if x['source_group']==g and x['metric']=='Arithmetic' and x['answer_layer']=='model' and x['model_id']=='M1')['within_group']['eligible_n'];short=g if g.startswith('JSON') else ('PDF '+g.split(':')[1][:12]+' 第'+g.split(':')[2]+'頁');rows.append([glabels[g],short,len(qids),l,a])
table('表4之7 原始來源群組及資格題數',['群組','原始紀錄或頁','題數','Logical','Arithmetic'],rows,[1.5,8.6,2,2.3,2.2],'source_dependency_summary.json 與source_group_influence.jsonl',8.5)
p('以原件SHA分組，三份原件分別支持'+ '、'.join(str(len(v))+'題' for _,v in sorted(dep['file_memberships'].items()))+'。原件層級與紀錄或頁層級的相關性均須揭露。')
p('本次逐群組計算群組內正確數與有效N，並計算排除該群組後的準確率及與全體的差值。此差值是樣本組成敏感度，不是來源的因果效果；若排除後無有效樣本則維持N/A。原件層級另作相同計算，避免只在10個群組內低估共享文件的依賴。')
rows=[]
for typ in ['Logical','Arithmetic']:
 for m in M:
  vals=[x['without_group']['accuracy'] for x in d['source_groups'] if x['metric']==typ and x['model_id']==m and x['answer_layer']=='model' and x['without_group']['accuracy'] is not None];rows.append([typ,m,pct(min(vals)),pct(max(vals))])
table('表4之8 排除單一來源群組後的原答準確率範圍',['指標','模型','最低','最高'],rows,[4.2,3,4.7,4.7],'source_group_influence.jsonl without_group accuracy',8.5)

h('六 原始模型與系統答案分離',True)
p('原始Faithfulness與Judge Relevance只要求answer可讀、非空且abstained明確為false，未把引用驗證通過設為評分前提。系統則另檢查來源適用性、凍結證據充分性與引用，可能拒絕同一原始回答，或以確定性證據摘取回補。因此Judge有效N與最終通過引用閘筆數不同，不能將兩者相減後直接稱為評分錯誤。')
table('表4之9 原答Judge樣本與系統處理流程',['模型','原答Judge N','原答引用通過¹','模型通過閘','確定性摘取','系統拒答','驗證失敗'],[[x['model_id'],x['raw_quality_valid_n'],x['raw_citation_pass_among_judge_valid'],x['final_model_generated'],x['deterministic_extraction'],x['system_abstained'],x['validation_failed']] for x in d['flows']],[1.2,2.8,2.9,2.5,2.4,2.4,2.4],'judge_denominator_explanation.json',8.3)
p('註¹：原答引用通過數僅統計具有原答Judge分數者，未要求證據充分。模型通過閘、確定性摘取、系統拒答與驗證失敗四類才互斥加總為每模型180筆。原始宣告拒答數分別為'+ '、'.join(x['model_id']+' '+str(x['raw_model_declared_abstention'])+'筆' for x in d['flows'])+'；不能與系統拒答混同。')
p('原始模型拒答或引用失敗而系統摘取成功時，保留DETERMINISTIC_EVIDENCE_EXTRACTION標記，不計為模型直接生成成功。Structured IFR只看原始模型JSON，M1為179/180，其餘為180/180；格式通過不代表完整語意指令遵循或專業答案正確。')
table('表4之10 保留的五筆系統非拒答缺陷',['模型','Question ID','內容缺陷','修正後計分'],[[x['model_id'],x['question_id'],'不完整條件句' if x['model_id']=='M2' else '題目複誦','相應BGE與Accuracy為N/A'] for x in d['special_cases']],[1.4,4.4,4.2,6.6],'incomplete_and_echo_cases_preserved_5.jsonl',8.5)
p('以上五筆原始origin不被追溯改寫。前輪已保存解析勘誤前後的衍生分數；本次逐筆重新對齊，沒有修改Judge原分數。品質Judge仍可能對問題複誦或不完整句給出偏高分；保存的一筆理由亦出現Goonch catfish與題目吳郭魚名稱不一致，顯示引用可定位與AI自評不能取代專業真值。')

h('七 六魚種結果與系統意義',True)
p('六魚種均保留30題，但來源資格與有效回答數並不均衡。表4之11呈現各模型原答BGE-M3平均及有效N；其餘Faithfulness、Logical、Arithmetic與題型分層見最終統計核對表。')
rows=[]
for sp,ls in d['breakdown']['species'].items():
 rows.append([sp,*[fmt(ls['model'][m]['bge_m3_cosine']['mean'])+' / '+str(ls['model'][m]['bge_m3_cosine']['n']) for m in M]])
table('表4之11 六魚種原始回答BGE-M3平均與有效N',['魚種',*M],rows,[3,3.4,3.4,3.4,3.4],'species_category_evidence_outcome_statistics.json species',8.8)
p('M2在全部可用回答上的BGE-M3平均為'+fmt(d['allstats']['model']['M2']['bge_m3_cosine']['mean'])+'，但有效N僅'+str(d['allstats']['model']['M2']['bge_m3_cosine']['n'])+'；拒答文字不納入該答案相關性均值。其TTFT較短也受到模型架構、輸出策略及首JSON內容定義影響，不能單獨解讀為專業服務品質較好。')
p('來源支持50題中，鰻魚與石斑魚各僅4題；Arithmetic資格未包含石斑魚。鱸魚題組依原工作簿金目鱸情境解讀，不泛化至全部鱸魚。題型分類部分承襲題庫啟發式分類，類別數量不等不宜直接比較總平均。')
p('系統在沒有可核驗專業依據時保留拒答，其餘130題沒有被一律視為應拒答真值。未有獨立真值的拒答率只能描述系統行為，不能稱為Abstention Correctness。先前六個固定安全政策案例可用於程式政策一致性，但不代表水產專家確認的無答案標準。')
p('系統層的Logical與Arithmetic可評估N更小，須與模型原答分開閱讀。系統引用閘可排除部分輸出，仍不能保證剩餘數值正確；上述五筆缺陷證明格式與來源位置檢查不能取代答案內容核驗。')

h('八 研究限制與結論',True)
for t in [
'第一，50題為來源核驗型探索性評估，並非人工專家Gold；參考答案及AI Judge仍有適用性與判定風險。Faithfulness衡量檢索證據支持程度，不能等同水產專業正確率。',
'第二，Accuracy只對可評估的實際回答計分，拒答或未解析答案維持N/A，可能產生選擇性回答偏差。因此同時保存應評估總數、有效N、正確數、錯誤數、不可評估數及correct/eligible；高answer-only Accuracy不代表高整體解題率。',
'第三，27題Logical及7題Arithmetic共同題目雖改善同題比較，仍屬小樣本，且共享少量來源。沒有因AI雙輪一致或獨立Judge而取得人工真值，亦未宣稱統計顯著性。',
'第四，P@5僅能報告12題探索性子集的0.30；不足五段或標註未充分者均維持N/A。語意相似、Reranker分數或來源metadata合格都不等於段落相關性真值。',
'第五，Arithmetic屬來源綁定的應用算術，不包含未完成協定核驗的FCR、SGR及bFCR。數值解析採單位錨點規則，前輪發現複誦輸入被誤當結果後已保存透明勘誤；未能可靠解析的單位或結果仍列N/A。',
'第六，效能指標受當時系統程序、模型卸載與暖機條件影響。RAM與VRAM是系統層級採樣，短暫峰值可能落在0.5秒採樣間隔之外；未量得Shared GPU Memory，未定義Memory Pressure或正式加權總分。',
'第七，原180題已參與多次Prompt、檢索及安全策略調整，不能宣稱全新Holdout。175題幹去重與15對近似題標記僅提供敏感度，不能消除所有知識依賴。']:
 p(t)
p('綜合而言，本研究已完成可重現的單一隔離Hybrid-RAG全流程及四模型720次新生成，並分離模型原答、系統安全閘、確定性摘取與拒答。固定共同題目的結果顯示各模型在不同指標呈現不同描述性表現；由於來源覆蓋、有效N與真值層級限制，本研究不建立未核准加權總分，亦不指定正式Winner。')
p('後續專業結論應以擴大合法且適用的原始證據、獨立專家審核及未參與開發的題組為基礎。現有結果可作系統效能、來源治理與有條件專業品質的探索性研究成果。')

h('九 統計追溯與重現方式',True)
p('本次僅離線讀取保存的JSONL與工作簿，沒有重新執行Generator、Judge或Embedding，也未修改Corpus或舊版分數。所有表格由保存的逐筆結果重新彙總，不以人工填補缺失值。')
table('表4之12 論文表格的資料依據',['用途','來源檔案'],[['原始生成及系統結果','generator_final_results_720.jsonl'],['Judge品質分數','judge_quality_detailed.jsonl'],['BGE答案相關性','bge_relevance_detailed.jsonl'],['Logical判定','logical_accuracy_detailed.jsonl'],['Arithmetic判定','arithmetic_accuracy_detailed.jsonl'],['共同題目逐題理由','paired_question_comparison_34.jsonl'],['來源依賴與敏感度','source_group_influence.jsonl 與 source_file_influence.jsonl'],['全部來源及雜湊','reproducibility_manifest.json']],[5,11.6],'凍結評測工作區與本次統計核對工作區',9)
p('原始結果工作區：'+I.name+'。本次核對工作區：'+W.name+'。完整模型digest、Corpus與Prompt版本、原始檔案及程式SHA、指標公式與分母均保存在Manifest及統計核對表。重新執行離線核對時使用明確的Python Interpreter與保存的相依套件版本，無須呼叫模型API。')
p('Repository pytest 607 passed及8 subtests passed、隔離測試19 passed及凍結前24個真實API情境，均為本次讀取的歷史驗收證據，並非本次重新執行。基線雜湊於本次工作前後另行核對；最終狀態以compatibility.json為準。')
wr('thesis_table_provenance.json',{'tables':tables,'numeric_inputs':'recomputed_data_package.json','all_tables_programmatically_generated':True,'new_inference_calls':0})
doc.core_properties.title='Corpus v3 凍結評測研究結果';doc.core_properties.subject='來源核驗型探索性四模型回歸評測';doc.core_properties.author='Marine Hybrid-RAG Research';doc.save(W/'thesis_results_chapter_zh_tw.docx')
limits='''資料限制聲明

1. Human Gold為0。50題為AUTO_SOURCE_VERIFIED來源核驗型探索性子集，依賴10組紀錄或PDF頁與3份原件，不能視為50筆獨立專家真值。
2. Logical與Arithmetic使用不同資格、不同有效N；All Available與共同題目配對均保留。拒答、複誦、無可靠答案或單位解析者為N/A，不填0。
3. Context Precision@5僅12題60段探索性子集，平均0.30，不推論全部180題。303段UNVERIFIED未改標。
4. Structured IFR只衡量原始JSON Schema，並非完整語意指令遵循或專業正確率。
5. Judge Faithfulness與Relevance評分原始可讀且非宣告拒答的answer，不要求先通過引用閘。它們不是水產專家準確率；本次未重評，已保留一筆理由中的魚種名稱矛盾。
6. BGE-M3 cosine為有效答案視圖，不以拒答文字、thinking、Context或Gold計算。本次只離線核算已保存分數的統計，不重算Embedding向量。
7. 系統確定性摘取不算模型直接生成成功。M2一筆不完整答案及M3四筆複誦的原始origin與勘誤前後分數均保留。
8. TTFT包含呼叫包裝器與取樣器初始化至首可見JSON內容，不是首個有意義答案字詞。TPS採引擎生成token／生成時間，可能含推理token。
9. RAM及Dedicated VRAM為每次系統層級採樣峰值的平均，0.5秒採樣，不是模型程序專屬量測；Shared GPU Memory與Memory Pressure為N/A。
10. 原180題已多次用於系統調整；175種題幹敏感度及15對近似題風險不能消除全部依賴，不是未曝光Holdout。
11. 小型配對與排除來源群組分析僅作描述性敏感度，不作總體顯著性、因果效果或正式Winner結論。
12. DGBAS僅2020描述性Fact；無年度鰻魚統計不補年度；藥品許可不推定劑量、停藥期或現行有效性。金目鱸資料不外推全部鱸魚。
13. 本次沒有新模型推論、Corpus變更、Production切換、權利範圍擴張或歷史分數覆寫。
'''
(W/'data_limitations_statement_zh_tw.txt').write_text(limits,encoding='utf-8')
print('DOCX and workbook source tables created',len(tables),flush=True)
if __name__=='__main__':pass
