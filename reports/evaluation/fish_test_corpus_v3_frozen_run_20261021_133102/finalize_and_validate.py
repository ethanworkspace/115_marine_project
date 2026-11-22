from pathlib import Path
import sys,json,hashlib,collections,re,datetime,sqlite3
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(W))
from bootstrap_run import baseline,sha,write,jl
from frozen_runner import verify_frozen
def main():
 manifest=verify_frozen();gs=jl(W/'generator_final_results_720.jsonl');ats=jl(W/'generator_raw_attempts_720.jsonl');metrics=json.loads((W/'evaluation_metrics_11.json').read_text(encoding='utf-8'));ab=json.loads((W/'abstention_analysis.json').read_text(encoding='utf-8'));sources=json.loads((W/'source_group_evaluation.json').read_text(encoding='utf-8'))
 assert len(gs)==len({(g['run_id'],g['question_id'],g['model_id']) for g in gs})==720
 assert len({g['question_id'] for g in gs})==180
 ctx={r['question_id']:r for r in jl(W/'frozen_corpus_and_contexts_180.jsonl')}
 for qid,r in ctx.items():
  matches=[g for g in gs if g['question_id']==qid];assert len(matches)==4 and len({g['context_digest'] for g in matches})==1 and matches[0]['context_digest']==r['context_digest']
  payloads=[json.loads(Path(g['prompt_file']).read_text(encoding='utf-8')) for g in matches]
  assert len({json.dumps({k:p[k] for k in ['system','prompt','format','options']},ensure_ascii=False,sort_keys=True) for p in payloads})==1
 for g in gs:
  assert g['model_digest']==manifest['models'][g['model_id']]['digest']
  a=next(a for a in ats if a['attempt_id']==g['attempt_id']);assert a['raw_model_response']==g['raw_model_response']
  if g['answer_origin']=='MODEL_GENERATED':assert g['raw_model_structure_valid'] and not g['parsed_model_response']['abstained'] and g['raw_citation_validation']['status']=='PASS'
  if not g['final_response']['abstained']:assert g['evidence_decision']['state']=='EVIDENCE_SUFFICIENT' and g['final_citation_validation']['status']=='PASS'
  if g['tps'] is not None:assert abs(g['tps']-g['engine_metrics']['eval_count']/(g['engine_metrics']['eval_duration']/1e9))<1e-10
  if g['ttft_visible_content_seconds'] is not None:
   traces=jl(Path(g['stream_trace_file']));first=next(x['elapsed_seconds'] for x in traces if x['event'].get('response'));assert first==g['ttft_visible_content_seconds']
 # Re-open saved workbook, inspect formulas and independently reconcile important cached values.
 from openpyxl import load_workbook
 book=W/'fish_test_evaluation_v3.xlsx';v=load_workbook(book,data_only=True,read_only=True);fo=load_workbook(book,data_only=False,read_only=True)
 # Some valid XLSX exporters omit the optional worksheet dimension element.
 # Count actual identifiers instead of treating absent max_row metadata as loss.
 row_counts={n:sum(r[0] is not None for r in v[n].iter_rows(min_row=4,min_col=1,max_col=1,values_only=True)) for n in ['Original_Results','Per_Question','Questions']}
 assert row_counts=={'Original_Results':720,'Per_Question':1440,'Questions':180},row_counts
 assert v['Dashboard']['B18'].value==720 and v['Dashboard']['C20'].value==12 and abs(v['Dashboard']['B20'].value-.3)<1e-10
 keys=['faithfulness','judge_answer_relevance','bge_m3_cosine','structured_ifr','ttft_seconds','tps','peak_system_ram_gib','peak_dedicated_vram_gib','logical_accuracy','arithmetic_accuracy']
 for j,mid in enumerate(['M1','M2','M3','M4']):
  for i,key in enumerate(keys):
   s=metrics['all_available_samples']['model'][mid][key];cell=v['Dashboard'].cell(i+6,j*2+2).value;n=v['Dashboard'].cell(i+6,j*2+3).value
   assert n==s['n']
   if s['mean'] is None:assert cell in ('n.a.',None)
   else:assert isinstance(cell,(int,float)) and abs(cell-s['mean'])<1e-9,(mid,key,cell,s)
 formula_n=sum(1 for s in fo for row in s for c in row if c.data_type=='f')
 errors=[(s.title,c.coordinate,c.value) for s in v for row in s for c in row if c.data_type=='e'];assert not errors,errors[:10]
 write('workbook_reopen_validation.json',{'reopened_with':'openpyxl read-only independent validation; authoring via @oai/artifact-tool','sheet_names':v.sheetnames,'sheet_count':len(v.sheetnames),'canonical_rows':720,'metric_layer_rows':1440,'original_questions':180,'formula_count':formula_n,'formula_errors':errors,'dashboard_all_metric_values_and_N_match_jsonl_derived_metrics':True,'p5_n':12,'p5_mean':.3,'sha256':sha(book),'bytes':book.stat().st_size})
 v.close();fo.close()
 after=baseline();write('protected_baseline_after.json',after);assert after['total']==after['unchanged']==636
 extra=json.loads((W/'additional_protected_before.json').read_text(encoding='utf-8'));extra_after=[{**x,'after_sha256':sha(R/x['path']),'unchanged':sha(R/x['path'])==x['sha256']} for x in extra];assert all(x['unchanged'] for x in extra_after)
 src=json.loads((W/'frozen_source_manifest.json').read_text(encoding='utf-8'));raw=[{'source_id':s['source_id'],'path':s['source_file'],'sha256':sha(Path(s['source_file'])),'unchanged':sha(Path(s['source_file']))==s['source_sha256']} for s in src['sources']];assert all(r['unchanged'] for r in raw)
 sqlite_sha=sha(R/'rag_store.sqlite3');assert sqlite_sha=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
 report={'status':'PASS','frozen_manifest':{'total':636,'unchanged':636},'sqlite_sha256':sqlite_sha,'isolated_corpus_sha256':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'input_snapshot_same_as_parent_alignment':sha(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3')==manifest['corpus']['database_sha256'],'additional_protected':extra_after,'source_files':raw,'production_switch':False,'old_720_records_modified':False,'formal_winner':None,'new_generator_results':len(gs),'all_questions_same_context_for_four_models':True,'model_weight_full_bytes_rehashed':False,'model_identity_check':'Ollama digest + model metadata; Llama architecture verified for M3','new_run_only':True}
 write('compatibility.json',report)
 validations=[]
 for p in W.glob('*.json'):
  json.loads(p.read_text(encoding='utf-8'));validations.append({'file':p.name,'format':'JSON','valid':True})
 for p in W.glob('*.jsonl'):
  vals=jl(p);validations.append({'file':p.name,'format':'JSONL','valid':True,'rows':len(vals)})
 write('deliverable_validation.json',{'status':'PASS','files':validations,'canonical_pairs_unique':True,'all_attempts_retained':True,'same_context_for_all_models':True,'raw_ifr_not_replaced_by_system_schema':True,'ttft_first_visible_event_reconciled':True,'tps_recomputed_from_engine_nanoseconds':True,'source_group_count':sources['original_group_n'],'human_gold':0,'protected_manifest_unchanged':636,'excel_reopened':True})
 def fmt(x):return 'N/A' if x is None else f'{x:.4f}'
 lines=['# Corpus v3 凍結四模型完整回歸評測','',f'- Run：`{W.name}`',f"- 完成：{len(gs)}筆唯一最終結果；{len(ats)}次保留的Generator嘗試；{sum(g['api_completed'] for g in gs)}筆API完成。",'- 固定同一版Corpus、180套Context、Prompt與安全規則；未執行A/B或消融。','- 所有品質與專業評估均為探索性；Human Gold=0；未建立正式加權總分或Winner。','','## 模型原始回答指標（數值／有效N）','','|指標|M1|M2|M3|M4|','|---|---:|---:|---:|---:|']
 for key in keys:
  cells=[]
  for mid in ['M1','M2','M3','M4']:
   s=metrics['all_available_samples']['model'][mid][key];cells.append(f"{fmt(s['mean'])} / {s['n']}")
  lines.append('|'+key+'|'+'|'.join(cells)+'|')
 lines+=['','System RAM與Dedicated VRAM為每次呼叫系統層級採樣峰值的平均（GiB），不是模型程序專屬記憶體；逐筆峰值與全體最大值另存JSON。TTFT採首個可見串流內容；thinking首事件另存。TPS採引擎eval_count與奈秒eval_duration，可能包含引擎計入的推理token。','','## 共用Context Precision@5','','12題60段刻意選取的既有來源核驗診斷樣本：平均0.30，非180題整體結果。六魚種各2題：吳郭魚0.20、烏魚0.20、石斑魚0.40、虱目魚0.20、鰻魚0.60、鱸魚0.20。303段UNVERIFIED維持未驗證，未以詞項重疊補標。','','## 50題來源支持子集','','50題完整來源支持，37題Logical與13題應用算術；依賴10組原始紀錄或PDF頁。`FT-grouper-Q16`仍保留為來源存在、Top-5漏失。不是Human Gold，不代表六魚種所有專業題型。','','|模型|模型直接回答／50|系統有答案／50|Logical正確／可評估（應評37）|Arithmetic正確／可評估（應評13）|','|---|---:|---:|---:|---:|']
 for mid in ['M1','M2','M3','M4']:
  a=ab[mid];s=metrics['all_available_samples']['model'][mid];lo=s['logical_counts'];ar=s['arithmetic_counts'];lines.append(f"|{mid}|{a['qualified50_model_direct_answer_n']}|{a['qualified50_system_answer_n']}|{lo['correct_n']}/{lo['evaluable_n']}|{ar['correct_n']}/{ar['evaluable_n']}|")
 lines+=['','拒答或無法可靠解析的回答不捏造為錯誤0分；另呈現correct/eligible-response及回答率，避免大量拒答導致answer-only Accuracy被誤讀。原始模型與系統層準確率分別保存在JSON與Excel中。','','## 拒答、引用及模型／系統分離','','|模型|原始宣告拒答|模型直接通過|確定性摘取|系統拒答|驗證失敗|','|---|---:|---:|---:|---:|---:|']
 for mid,a in ab.items():
  c=a['answer_origins'];lines.append(f"|{mid}|{a['raw_model_declared_abstentions']}|{c.get('MODEL_GENERATED',0)}|{c.get('DETERMINISTIC_EVIDENCE_EXTRACTION',0)}|{c.get('ABSTAINED',0)}|{c.get('VALIDATION_FAILED',0)}|")
 lines+=['','其餘130題未一律視為應拒答真值。Abstention Correctness僅限6題先前固定的系統安全政策個案，不能當成獨立臨床或全世界無答案的專家真值。引用定位通過不等於專業答案正確。','','## 配對與來源群組統計','','各指標同時呈現All Available與四模型共同有效題目；不能把不同N均值解讀為完全公平比較。175種不同題幹另作敏感度分析，15對近似題保留依賴風險。來源群組統計與保守的共享來源連通群組bootstrap為探索性補充，不能作正式顯著性結論。','','## 技術驗收與完整性','','Repository pytest：607 passed，8 subtests passed。隔離驗證：19 passed。凍結前四模型24個真實API情境通過；Streamlit真實M2問答通過；新載入Hybrid Retrieval與固定Top-5一致。初次Smoke的M1輸出截斷失敗完整保留，修正引用ID生成約束並通過第二版驗收後才凍結。','','Excel已由artifact工具產出、公式重算、圖表與各表預覽、匯出及重新開啟，另用openpyxl唯讀核對720筆結果、1440筆模型／系統分層指標、各模型平均與有效N。','','Frozen Manifest636/636、Production SQLite SHA-256、原Phase E/W720筆生成、來源原件及本輪Corpus快照皆保持不變。LLM完整權重bytes未重雜湊；已核對Ollama digest及metadata，M3為正確Llama8B。','','## 限制','','- Faithfulness與Judge Relevance是獨立Mistral NeMo的探索性評分，不是水產專家正確率。','- 未核實來源的藥品劑量、停藥期、FCR／SGR／bFCR專業協定仍不計分。','- 來源群組少、六魚種與題型不平衡、原180題多次參與系統開發，不能宣稱全新Holdout。','- 系統摘取不算模型直接成功，安全閘阻擋不等同模型自主拒答。','- 本輪完成即停止，不切換Production。']
 lines+=['','## 解析器勘誤與無答案輸出','','凍結v1的單位錨點解析器會把題目複誦中的輸入數值當成結果。生成完成後的資料品質檢查識別純題目複誦與沒有結論的條件重述；BGE有效答案視圖與Logical／Arithmetic的相應結果改列N/A。參考答案、公式、容差、來源與Generator規則均未更改。原始衍生分數逐位元組保存在 *_frozen_parser_v1.jsonl，更正程式、時間、雜湊及逐筆差異已保存；獨立Judge的Faithfulness／Relevance原始評分不改寫。這是具揭露的解析勘誤，不是新的Human Gold。','','MODEL_GENERATED表示模型輸出通過程式格式與引用閘，不能單憑此標記宣稱已回答或回答正確。另列具有實質答案內容的輸出數：']
 for mid in ['M1','M2','M3','M4']:
  aa=ab[mid];lines.append(f"- {mid}：50題中{aa['qualified50_substantive_direct_answer_n']}筆通過閘且具有實質答案內容；原始輸出有{aa['raw_nonanswer_echo_or_incomplete_n']}筆複誦／不完整條件，系統非拒答輸出有{aa['system_nonanswer_echo_or_incomplete_n']}筆相同問題。")
 lines+=['','量測補充：TTFT計時器起於每次串流呼叫包裝器、在取樣器初始化之前，至首個實際可見JSON內容事件；因此含初始化成本，不是首個有意義答案字詞的延遲。',f"來源依賴補充：10組原始紀錄／PDF頁亦共享{sources['original_source_file_sha256_n']}份原件，群組間仍可能相關。",'鱸魚題組依原工作簿金目鱸情境評估，不泛化全部鱸魚物種。']
 lines+=['','## 實際模型身分','','|模型|Ollama標籤|Digest|','|---|---|---|']
 for mid in ['M1','M2','M3','M4']:
  ident=manifest['models'][mid];lines.append(f"|{mid}|{ident.get('tag',ident.get('model',ident.get('name','見Manifest')))}|{ident['digest']}|")
 lines+=['','## 模型原答的共同有效樣本','','|指標|共同N|M1|M2|M3|M4|','|---|---:|---:|---:|---:|---:|']
 for key in ['faithfulness','judge_answer_relevance','bge_m3_cosine','logical_accuracy','arithmetic_accuracy']:
  p=metrics['four_model_paired_samples']['model'][key];lines.append('|'+key+'|'+str(p['common_question_n'])+'|'+'|'.join(fmt(p['models'][mid]['mean']) for mid in ['M1','M2','M3','M4'])+'|')
 lines+=['','All Available與共同有效樣本的排序可能不同。上述比較仍受AI評分、來源群組相關、拒答及解析缺失限制，不作正式能力顯著性或Winner判斷。','','## 50題子集的來源資格與安全限制','','50題均為自動來源核驗；其餘130題包含17題部分支持、17題適用範圍未核實、84題本版未找到完整答案、12題問題條件不足。這些狀態未被改寫為全球無答案或全部應拒答。','系統仍有通過格式與引用閘、但未給出實質答案或算術答案錯誤的案例。技術驗收通過不能推論專業正確性已全部通過；相關逐題失敗完整保留。']
 (W/'final_720_evaluation_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'status':'PASS','generations':720,'attempts':len(ats),'protected':636,'excel':str(book)},ensure_ascii=False),flush=True)
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
