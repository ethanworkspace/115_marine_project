import sys,json,collections,statistics
sys.dont_write_bytecode=True
from fair_grounded_rag import W,I,MODELS,jl,write
from bootstrap_repair import sha
def main():
 summary=json.loads((W/'regression_model_comparison.json').read_text(encoding='utf-8'));safe=json.loads((W/'safety_regression_summary.json').read_text(encoding='utf-8'));app=json.loads((W/'streamlit_real_validation.json').read_text(encoding='utf-8'));compat=json.loads((W/'compatibility.json').read_text(encoding='utf-8'));refs={r['question_id']:r for r in jl(W/'verified_reference_answers_v3.jsonl')};rows=jl(W/'shared_contexts_180.jsonl');gens=jl(W/'regression_results_200_final.jsonl');allscore={k:jl(W/('arithmetic_regression_detailed_v4.jsonl' if k=='arithmetic' else f'{k}_regression_detailed.jsonl')) for k in ['logical','arithmetic']}
 gaps=[]
 for r in rows:
  e=r['evidence_packet'];ref=refs[r['question_id']];gaps.append({'question_id':r['question_id'],'original_question':r['question'],'species':r['species'],'category':r['category'],'context_count':len(r['top5']),'evidence_state':e['state'],'required_answer_elements':e['required_answer_elements'],'missing_information':e['missing_information'],'original_reference_eligibility':ref.get('eligibility'),'source_qualified_for_task_scoring':bool(ref.get('logical_rubric') or ref.get('expected_calculation')),'qualification_does_not_mean_human_gold':True,'not_found_in_retrieved_context_is_not_global_no_answer_truth':True})
 (W/'answerability_and_missing_information_180.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in gaps),encoding='utf-8')
 groupids=sorted({k for g in gens for k in g['source_group_ids']});group=[]
 for gid in groupids:
  for metric,scores in allscore.items():
   for mid in MODELS:
    for layer in ['model','system']:
     ss=[s for s in scores if s['model_id']==mid and s['answer_layer']==layer and gid in s['source_group_ids']]
     if ss:group.append({'source_group_id':gid,'metric':metric,'model_id':mid,'answer_layer':layer,'question_ids':[s['question_id'] for s in ss],'fixed_question_n':len(ss),'correct_n':sum(s['verdict']=='correct' for s in ss),'validated_task_success_n':sum(s['validated_task_success'] for s in ss),'not_evaluable_n':sum(s['verdict']=='not_evaluable' for s in ss),'dependency_warning':'A question with several source groups is associated with each; group rows must not be summed as independent questions.'})
 write('source_group_regression_results.json',{'source_group_n':len(groupids),'human_gold_n':0,'groups':group,'no_independence_or_significance_claim':True})
 positive={g['question_id']:g for g in gens};species={s:{'qualified_question_n':sum(r['species']==s for r in positive.values()),'logical_n':sum(r['species']==s and bool(refs[r['question_id']].get('logical_rubric')) for r in positive.values()),'arithmetic_n':sum(r['species']==s and bool(refs[r['question_id']].get('expected_calculation')) for r in positive.values())} for s in sorted({r['species'] for r in rows})}
 tests=json.loads((W/'repository_pytest_results.json').read_text(encoding='utf-8'));arith_app=json.loads((W/'streamlit_arithmetic_validation.json').read_text(encoding='utf-8'))
 tech=tests['repository']['passed']==607 and tests['isolated_final_policy_and_tokenizer']['passed']==47 and arith_app['passed'] and len(gens)==200 and all(g['api_completed'] for g in gens) and len(jl(W/'safety_results_24_final.jsonl'))==24 and not safe['behavior_failures'] and app['passed'] and compat['frozen_manifest_unchanged']==636
 readiness={'technical_readiness':{'ready_for_authorized_future_720':tech,'scope':'Actual four-model source-bound API regression + safety cases + real Streamlit/API test + formal607 tests + final isolated policy/tokenizer tests; does not certify every future answer','full720_started':False},'scoring_readiness':{'source_verified_question_ids':50,'logical_fixed_n':37,'arithmetic_fixed_n':13,'human_gold_n':0,'model_and_system_scored_separately':True,'fixed_denominator_task_success_policy':str(W/'fixed_denominator_scoring_policy.json'),'conditional_accuracy_preserved':True,'all_other130_not_automatically_abstention_gold':True,'faithfulness_relevance':'Use own eligible readable-answer samples, never force N=180','context_precision':'Exactly unchanged5-chunk contexts permit reusing12 historical exploratory labels; other changed contexts need reliable labels. No reranker or keyword substitution','newly_annotated_p5_n':0,'reused_valid_p5_n':12,'reused_exploratory_p5_mean':0.30,'professional_metric_status':'AUTO_SOURCE_VERIFIED conditional exploratory subset, not expert-confirmed accuracy'},'research_representativeness':{'six_species':species,'source_group_n':len(groupids),'original_source_file_n':3,'category_counts':json.loads((W/'reference_subset_coverage.json').read_text(encoding='utf-8'))['categories'],'limited':True,'not_unseen_holdout':True,'no_all180_professional_accuracy_claim':True},'future_full_run_conditions':['Use final_active_policy_manifest and fixed shared_contexts_180 without mid-run changes','180/model fixed for completion, direct grounded, abstention and invalid-output rates','Logical37 and Arithmetic13 task denominators fixed; refusals/failures remain unsuccessful','Preserve raw model output, every API attempt, final system origin and all missing reasons','Model-only answers and deterministic extraction scored separately; no weighted Winner'],'historical_production_unchanged':True,'no_automatic_launch':True}
 write('next_full_evaluation_readiness.json',readiness)
 def pct(x):return f'{100*x:.2f}%'
 table=['|模型|原始 JSON 有效 /50|模型直接完整回答 /50|系統完整回答 /50|來源 Rubric 確認且通過閘的模型回答 /50|模型主動拒答|最終驗證失敗|','|---|---:|---:|---:|---:|---:|---:|']
 tasks=['|模型|Logical 任務成功 /37|Logical 條件式準確率（有效 N）|Arithmetic 任務成功 /13|Arithmetic 條件式準確率（有效 N）|','|---|---:|---:|---:|---:|']
 for mid,d in summary['models'].items():
  table.append(f"|{mid}|{d['response_completion']['numerator']}|{d['model_grounded_answer_rate']['numerator']}|{d['system_grounded_answer_rate']['numerator']}|{d['model_source_rubric_confirmed_grounded_rate']['numerator']}|{d['raw_abstention_rate']['numerator']}|{d['final_validation_failure_rate']['numerator']}|")
  l=d['logical']['model'];a=d['arithmetic']['model']
  def ca(x):return ('N/A' if x['conditional_accuracy'] is None else pct(x['conditional_accuracy']))+f"（N={x['conditional_accuracy_valid_n']}）"
  tasks.append(f"|{mid}|{l['validated_task_success_n']}/37 ({pct(l['validated_task_success_rate'])})|{ca(l)}|{a['validated_task_success_n']}/13 ({pct(a['validated_task_success_rate'])})|{ca(a)}|")
 prep=json.loads((W/'retrieval_preparation_summary.json').read_text(encoding='utf-8'));parser=json.loads((W/'postprocessing_change_audit_final.json').read_text(encoding='utf-8'))
 report=f'''# 四模型全題作答策略與公平評測修正結果

## 實際完成範圍

已修改可執行的隔離 RAG；本次完成 **50 題 × 4 模型 = 200 筆新生成**及 **6 類安全／部分證據案例 × 4 模型 = 24 筆**。另有兩輪八次預檢、Streamlit 真實 API 測試與暖機，均獨立標記，不混入 200 筆分母。沒有執行新的完整 720 次生成，也未修改先前 720 筆。

## 50 題共同來源支持子集

{chr(10).join(table)}

「模型直接完整回答」是來源與引用程式篩檢通過，不直接等同內容全部正確；第四個數值欄另要求凍結來源 Rubric 的正確判定。所有題目均非 Human Gold。系統欄含確定性摘取，不能當成模型能力。

## 固定分母的任務成功率

{chr(10).join(tasks)}

主要任務成功率要求內容正確且通過 JSON／來源／Citation 完整作答閘。未成功、拒答及無法判讀都留在固定分母。條件式準確率另以實際可評估內容計算，原始內容正確但引用未過、或模型仍標為部分回答者，可能仍屬條件式內容正確；兩者定義不同。內容任務成功率、系統層結果及逐題理由保存在 JSONL／JSON，不覆寫歷史分數。

## 檢索與證據狀態

針對首輪未充分支持的 {prep['supplemented']} 題，各執行至多一次已准入 Corpus 補充混合檢索與有限同 Record 章節展開。查詢未讀取四模型答案或計算參考結果欄位，但使用既有需求描述，選取亦使用已知來源條款；屬來源已知的回歸補檢，不是未接觸答案方向的盲測。180 題中 {prep['any_context']} 題有實際 Context，{prep['full_top5']} 題有五筆；這是檢索覆蓋，不是答案支持率。50 題來源支持子集現均取得必要來源條款，原 FT-grouper-Q16 漏失的必要片段已召回。

其餘題目分為 17 題部分來源支持、94 題尚缺充分核驗的支持元素，以及19題高風險用藥／法規依據未核實。這些狀態不能改稱全世界沒有答案；逐題缺口見 answerability_and_missing_information_180.jsonl。沒有新增來源、變更原始 Corpus、擴張藥品許可或 DGBAS 用途。

## 真實驗收及失敗保留

Repository tests/ 實際 **607 passed、8 subtests passed，0 failed／skipped／collection error**。最終隔離政策、數值 tokenizer、算術結果辨識與部分證據缺口處理合計 **47 passed**，另存完整輸出。Streamlit AppTest實際呼叫M2的有據與無據情境，另以M1完成算術情境真實API驗證，確認同版 Corpus SHA、回答、來源版本與定位、拒答缺口顯示；沒有以 Mock 代替 Generator。四模型的有據、部分、無 Context、錯魚種、藥品依據不足、法規版本不明及缺條件行為均留真實呼叫紀錄。

24個案例的系統協定層處理均完成，其中20個無據／錯物種／高風險案例的最終系統皆保留不足證據，沒有輸出具體未核驗劑量或停藥期。這不是24/24專業內容正確：M1部分證據回答將適溫過度概括成「健康且良好」；M3部分回答有自相矛盾，以及原始法規拒答中的「可能不合法」猜測（該猜測未進入最終系統答案）。M4原始回答未揭露部分來源限制，系統才補入既有缺口。詳 safety_raw_vs_system_review.jsonl；這些警示不因JSON或引用通過而消失。

預檢發現重複引用與條列數值誤判，於生成前修復並凍結。200 次生成期間不改 Prompt、Context 或安全規則。另在完整生成結束後確認數值解析器會把「30°C，30°C」的標點移除後誤抓尾數，以及把合法 Chunk ID 的編號當成專業數值；統一修正 tokenizer，並在來源已確認為部分支持時允許系統補入既有缺口（不修改模型原始欄位，且強制維持ANSWERED_PARTIAL），重播全部224筆既有原始輸出，{parser['changed_fields_record_n']}筆後處理欄位有差異，其中{parser['changed_status_or_origin_n']}筆答案狀態或來源分類改變。原始生成與初次後處理全數保存，無重新生成、無依正確答案或Question ID選擇性修正；最終所有模型使用同一修正。另修正算術解析器會誤取最後一個單位數值的問題，改為先辨識結果語句／公式右側及輸入運算元、密度與總量，候選選擇不比對參考答案；只在選定後用凍結參考值與容差計分。已保留原解析結果與全部中間快照。真正未受支持的百分比、數值、錯誤算術與題目複誦仍會被擋下。語意支持與因果關係仍可能漏判，不宣稱這套程式篩檢等同專家全文核驗。

## 後續 180 題 × 四模型的公平性

完整回歸使用同一180個Question ID及同一凍結Context；五項完成／回答／拒答／無效率皆使用180分母。這次新生成僅50題／模型，報50分母；已另以原720筆離線重算既有180分母指標，不把舊、新生成混成一批。

Logical固定37題、Arithmetic固定13題，不因拒答刪題。保留每題、每模型、原始模型與系統結果、同來源群組、原條件式準確率。Faithfulness、Relevance、BGE及P@5不強行補值。已逐段比對原12題P@5的五個Chunk ID、順序、全文與來源版本，全部與本輪相同，故保留原探索性P@5平均0.30（N=12）；沒有新標註，不外推180題，其餘改變的Context不移植標籤。

## 下一次720次評測就緒

本介面使用固定180題及凍結來源輪廓，不宣稱已驗證任意新問題的泛化能力。

技術就緒：**{'通過本輪指定案例，可在另行授權後執行完整回歸' if tech else '仍有未通過項目，詳 readiness JSON'}**。可計分性：50題自動來源核驗子集，Logical37、Arithmetic13，可報固定分母任務成功與條件式準確率。代表性：六魚種皆有樣本，但數量不均，50題僅依賴10組來源紀錄／PDF頁、3份原件；沒有人工專家Gold或全新Holdout，不能據此推論整體水產專業能力。模型仍可能產生錯答或複誦，應在完整回歸中如實計為任務未成功。

本輪不自動啟動720次，不建立加權總分或Winner。

## 保護及重現

Frozen Manifest **{compat['frozen_manifest_unchanged']}/636**一致；正式SQLite SHA-256維持 `{compat['production_sqlite_sha256']}`。既有隔離 Corpus SHA、原Phase E／W生成與歷史凍結run檔案均重新核對不變。模型身分用實際Ollama digest及architecture核對，M3為Llama架構；本輪未重新逐byte雜湊整份模型權重。正式環境沒有切換。

啟用入口：fair_streamlit_app_final.py；最終引擎：fair_grounded_rag_final.py。answer_policy_frozen_manifest.json保存生成時凍結設定，final_active_policy_manifest.json保存統一修正後的使用版本。全部API Prompt、原始串流、失敗嘗試、Context與逐題分數均可追溯。
'''
 (W/'final_answer_repair_report.md').write_text(report,encoding='utf-8')
 write('reproducibility_manifest.json',{'workspace':str(W),'historical_run':str(I),'active_app':'fair_streamlit_app_final.py','active_engine':'fair_grounded_rag_final.py','generation_freeze':'answer_policy_frozen_manifest.json','final_policy_freeze':'final_active_policy_manifest.json','positive_raw_generations':200,'safety_raw_generations':24,'no_new_full720':True,'scoring_policy':'fixed_denominator_scoring_policy.json','all_evaluable_scores_level':'AUTO_SOURCE_VERIFIED; AI_ASSISTED; NOT_HUMAN_GOLD','historical_data_modified':False,'key_files':[{'path':p.name,'sha256':sha(p)} for p in sorted(W.iterdir()) if p.is_file() and p.suffix in ['.py','.json','.jsonl','.txt','.md','.csv'] and p.name!='reproducibility_manifest.json']})
 print('Final report, answer gap180, source groups and future-run readiness written',flush=True)
if __name__=='__main__':main()
