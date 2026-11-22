import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const W=path.dirname(fileURLToPath(import.meta.url));
const read=async n=>JSON.parse(await fs.readFile(path.join(W,n),'utf8'));
const jl=async n=>(await fs.readFile(path.join(W,n),'utf8')).trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
const [metrics,per,logic,arith,p5,source,paired,dims,refs,mf,rec,valid,compat,dup]=await Promise.all([
 read('evaluation_metrics_11.json'),jl('per_question_metrics.jsonl'),jl('logical_accuracy_detailed.jsonl'),jl('arithmetic_accuracy_audited.jsonl'),jl('context_precision_detailed.jsonl'),read('source_group_evaluation.json'),read('paired_sample_comparison.json'),read('species_category_comparison.json'),jl('verified_reference_answers_v3.jsonl'),read('final_run_frozen_manifest.json'),read('deployment_model_recommendation.json'),read('statistical_validation.json'),read('compatibility.json'),read('duplicate_sensitivity.json')]);
const pytest=await read('repository_pytest_results.json');
const identity=await read('model_runtime_identity.json');
const wb=Workbook.create();
const names=['Dashboard','Fixed_Denominators','Metrics_11','Efficiency','Logical','Arithmetic','Context_Precision','Species','Categories','Source_Groups','Paired','Duplicate_Sensitivity','Per_Question','Raw_Generation','References','Frozen_Settings','Errors_Limits','Validation'];
const sheets=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const val=x=>x===undefined?null:(typeof x==='object'&&x!==null?JSON.stringify(x):typeof x==='string'&&x.startsWith('=')?"'"+x:x);
const font='Arial';const blue='#21445F',ink='#172C3A',amber='#FFF0CC';
function table(name,title,headers,rows,widths=[]){
 const s=sheets[name];s.showGridLines=false;let end=col(headers.length-1),last=rows.length+5;
 s.getRange(`A1:${end}${Math.max(last,8)}`).format.font={name:font,size:10,color:ink};
 s.getRange('A2').values=[[title]];s.getRange('A2').format.font={name:font,size:14,bold:true,color:ink};
 s.getRange(`A5:${end}5`).values=[headers];if(rows.length)s.getRange(`A6:${end}${last}`).values=rows.map(r=>r.map(val));
 s.getRange(`A5:${end}5`).format={fill:blue,font:{name:font,size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:48,verticalAlignment:'center',horizontalAlignment:'center'};
 s.getRange(`A6:${end}${Math.max(last,6)}`).format={wrapText:true,verticalAlignment:'top',rowHeight:24};
 for(let c=0;c<headers.length;c++)s.getRange(`${col(c)}5:${col(c)}${Math.max(last,6)}`).format.columnWidth=widths[c]??18;
 // Fit wrapped source text and IDs; keep original full JSONL authoritative.
 for(let i=0;i<rows.length;i++){
  let lines=1;
  for(let c=0;c<headers.length;c++){
   const value=val(rows[i][c]);if(typeof value!=='string')continue;
   const width=widths[c]??18;
   const textLines=value.split('\n');
   lines=Math.max(lines,textLines.reduce((n,t)=>n+Math.max(1,Math.ceil([...t].reduce((sum,ch)=>sum+(ch.charCodeAt(0)>255?1.8:1),0)/Math.max(width-2,8))),0));
  }
  s.getRange(`A${i+6}:${end}${i+6}`).format.rowHeight=Math.min(360,Math.max(24,lines*14+6));
 }
 if(rows.length){const t=s.tables.add(`A5:${end}${last}`,true,`Data_${name}`);t.showFilterButton=true;}
 if(rows.length>20){s.freezePanes.freezeRows(5);s.freezePanes.freezeColumns(2);}
 return s;
}
const fields=['question_id','model_id','species','category','evidence_state','professional_metric','raw_schema_valid','raw_response_completed','model_direct_complete','source_screened_model_answer','raw_abstained','system_abstained','system_validation_failed','raw_citation_failure','deterministic_extraction','incomplete_answer','model_task_success','model_content_verdict','system_task_success','answer_origin','final_status','faithfulness','judge_answer_relevance','bge_cosine','ttft_seconds','tps','system_ram_peak_gib','dedicated_vram_peak_gib','source_group_ids','validation_reason','quality_missing_reason','bge_missing_reason','context_digest','prompt_sha256'];
const measured=['faithfulness','judge_answer_relevance','bge_cosine','ttft_seconds','tps','system_ram_peak_gib','dedicated_vram_peak_gib'];
fields.push(...measured.map(k=>k+'_metric_valid'));
const pdata=per.map(x=>fields.map(k=>k.endsWith('_metric_valid')?+Number.isFinite(x[k.slice(0,-13)]):typeof x[k]==='boolean'?+x[k]:x[k]));
table('Per_Question','720筆逐題模型與系統結果',fields,pdata,[22,12,12,22,32,16]);
const range=k=>`'Per_Question'!$${col(fields.indexOf(k))}$6:$${col(fields.indexOf(k))}$725`;
const modelrange=range('model_id');
function count(m,k,v=1){return `COUNTIFS(${modelrange},"${m}",${range(k)},${typeof v==='number'?v:'"'+v+'"'})`;}
function nvalid(m,k){return `SUMIFS(${range(k+'_metric_valid')},${modelrange},"${m}")`;}
function mean(m,k){return `IF(${nvalid(m,k)}=0,"n.a.",SUMIFS(${range(k)},${modelrange},"${m}")/${nvalid(m,k)})`;}
const mids=Object.keys(metrics.models);const fixedheaders=['Model','N180','原始JSON N','JSON完成率','直接完整回答N','直接完整回答率','來源篩檢回答N','來源篩檢回答率','50題成功N','50題成功率','Logical37成功N','Logical成功率','Arithmetic13成功N','Arithmetic成功率','原始拒答N','原始拒答率','不完整回答N','不完整回答率','引用失敗N','引用失敗率','系統摘取N','系統摘取率'];
const fixed=table('Fixed_Denominators','四模型固定分母',fixedheaders,mids.map(m=>[m,...Array(fixedheaders.length-1).fill(null)]));
for(let i=0;i<4;i++){
 const m=mids[i],r=i+6;fixed.getRange(`B${r}:V${r}`).formulas=[[
 `=COUNTIFS(${modelrange},"${m}")`,`=${count(m,'raw_schema_valid')}`,`=C${r}/B${r}`,`=${count(m,'model_direct_complete')}`,`=E${r}/B${r}`,`=${count(m,'source_screened_model_answer')}`,`=G${r}/B${r}`,`=${count(m,'model_task_success')}`,`=I${r}/50`,
 `=COUNTIFS(${modelrange},"${m}",${range('professional_metric')},"Logical",${range('model_task_success')},1)`,`=K${r}/37`,`=COUNTIFS(${modelrange},"${m}",${range('professional_metric')},"Arithmetic",${range('model_task_success')},1)`,`=M${r}/13`,
 `=${count(m,'raw_abstained')}`,`=O${r}/B${r}`,`=${count(m,'incomplete_answer')}`,`=Q${r}/B${r}`,`=${count(m,'raw_citation_failure')}`,`=S${r}/B${r}`,`=${count(m,'deterministic_extraction')}`,`=U${r}/B${r}`]];
}
for(const c of ['D','F','H','J','L','N','P','R','T','V'])fixed.getRange(`${c}6:${c}9`).setNumberFormat('0.0%');
const metricDefs=[['Faithfulness','faithfulness','0–1','既有獨立Judge；僅可閱讀且非拒答的模型正文'],['Judge Relevance','judge_answer_relevance','0–1','既有獨立Judge；非專業正確率'],['BGE-M3 Cosine','bge_cosine','cosine','問題與非拒答正文；不包含thinking或標準答案'],['Structured IFR','raw_schema_valid','ratio','原始JSON Schema；系統回補不計模型通過'],['TTFT','ttft_seconds','s','串流第一個非空response事件；thinking另存'],['TPS','tps','token/s','eval_count/(eval_duration_ns/1e9)'],['System RAM','system_ram_peak_gib','GiB','每次推論系統層級採樣峰值之平均'],['Dedicated VRAM','dedicated_vram_peak_gib','GiB','GPU裝置採樣峰值之平均；非模型程序專屬'],['Context Precision@5',null,'ratio','共用12題相同Context探索性子集，非全180題'],['Logical Accuracy',null,'ratio','條件式正確率；另列固定37題任務成功率'],['Arithmetic Accuracy',null,'ratio','條件式正確率；另列固定13題任務成功率']];
const mr=[];for(const m of mids)for(const [name,key,unit,scope] of metricDefs)mr.push([m,name,null,null,unit,scope]);
const ms=table('Metrics_11','11項指標與有效樣本數',['Model','Metric','Mean / Rate','Valid N','Unit','Definition'],mr,[12,25,18,12,14,82]);
for(let i=0;i<mr.length;i++){
 const [m,name]=mr[i],r=i+6;const def=metricDefs.find(d=>d[0]===name),key=def[1];let value,n;
 if(key==='raw_schema_valid'){value=`${count(m,key)}/180`;n='180';}
 else if(key){value=mean(m,key);n=nvalid(m,key);}
 else if(name==='Context Precision@5'){value=`AVERAGE('Context_Precision'!$F$6:$F$185)`;n=`COUNT('Context_Precision'!$F$6:$F$185)`;}
 else {const p=metrics.models[m].professional.model[name==='Logical Accuracy'?'logical':'arithmetic'];ms.getRange(`C${r}:D${r}`).values=[[p.conditional_accuracy,p.conditional_n]];continue;}
 ms.getRange(`C${r}:D${r}`).formulas=[[`=${value}`,`=${n}`]];
}ms.getRange('C6:C49').setNumberFormat('0.0000');
const ef=table('Efficiency','真實推論效能與系統採樣',['Model','Question ID','TTFT s','TPS token/s','Wall s','Output Tokens','Engine ns','RAM peak GiB','VRAM peak GiB','Shared GPU','Scope'],per.map(x=>[x.model_id,x.question_id,x.ttft_seconds,x.tps,x.wall_seconds,x.eval_count,x.eval_duration_ns,x.system_ram_peak_gib,x.dedicated_vram_peak_gib,null,'system_level_sampled_peak']),[12,22,14,16,14,14,20,18,18,14,32]);ef.getRange('C6:E725').setNumberFormat('0.000');ef.getRange('H6:I725').setNumberFormat('0.00');
for(const [name,rows] of [['Logical',logic],['Arithmetic',arith]]){
 table(name,`${name}來源判準評分`,['Model','Question ID','Answer layer','Verdict','Task success','Content correct','Species','Source groups','Reason','Observed answer','Rubric SHA','Original parser verdict','Original parser reason'],rows.map(x=>[x.model_id,x.question_id,x.answer_layer,x.verdict,+x.validated_task_success,+x.fixed_denominator_success,x.species,x.source_group_ids,x.reason,x.raw_answer_text,x.rubric_sha256,x.original_automatic_verdict??null,x.original_automatic_reason??null]),[12,22,16,20,16,16,12,42,75,85,40,26,75]);
}
const cp=table('Context_Precision','共用檢索P@5的有效性',['Question ID','Species','Category','Actual contexts','Valid label N','P@5','Status','Reason','Context SHA'],p5.map(x=>[x.question_id,x.species,x.category,x.top5_count,x.effective_n_chunks,x.p_at_5,x.status,x.reason,x.context_digest]),[22,12,24,18,18,12,48,55,40]);cp.getRange('F6:F185').setNumberFormat('0.00');
for(const [name,key,title] of [['Species','species','六魚種固定分母與有效樣本'],['Categories','category','題型固定分母與有效樣本']]){
 table(name,title,['Species / Category','Model','All N','Direct complete N','Abstention N','Qualified N','Task success N','Task rate','Faithfulness','F N','Relevance','R N','BGE','BGE N','TTFT s','TPS'],dims[key].map(x=>[x.value,x.model_id,x.all_n,x.direct_complete_n,x.raw_abstained_n,x.qualified_n,x.qualified_task_success_n,x.qualified_task_success_rate,x.faithfulness.mean,x.faithfulness.n,x.relevance.mean,x.relevance.n,x.bge.mean,x.bge.n,x.ttft.mean,x.tps.mean]),[24,12,12,20,18,16,20,16,18,12,16,12,14,12,14,14]);sheets[name].getRange(`H6:P${dims[key].length+5}`).setNumberFormat('0.000');
}
table('Source_Groups','10組來源依賴',['Source group','Model','Question N','Logical N','Arithmetic N','Model success N','System success N','Model success rate','System success rate','Question IDs'],source.group_rows.map(x=>[x.source_group_id,x.model_id,x.n,x.logical_n,x.arithmetic_n,x.model_task_success_n,x.system_task_success_n,x.model_task_success_rate,x.system_task_success_rate,x.question_ids]),[52,12,16,16,16,20,20,23,23,65]);
table('Paired','四模型共同有效題目',['Metric','Model','Common N','Mean / Rate','Question IDs','Limit'],Object.entries(paired).flatMap(([metric,x])=>mids.map(m=>[metric,m,x.common_n,x.models[m].mean,x.question_ids,'同題配對描述性結果；不宣稱顯著性'])),[25,12,16,18,80,52]);
table('Duplicate_Sensitivity','175種題幹敏感度',['Model','Original N','Dedup N','Qualified N','Task success N','Faithfulness','F N','Dependence'],mids.map(m=>[m,180,dup.models[m].n,dup.models[m].source_qualified_n,dup.models[m].source_task_success_n,dup.models[m].faithfulness.mean,dup.models[m].faithfulness.n,'保留跨魚種180題；15對近似題仍具有依賴']),[12,16,16,18,22,20,12,70]);
table('Raw_Generation','原始輸出與系統最終輸出',['Model','Question ID','Raw model response','Final system answer','Answer origin','Raw validation reason','Attempt ID','Prompt path','Stream path','Context SHA','Model digest'],per.map(x=>[x.model_id,x.question_id,x.raw_model_response,x.final_answer,x.answer_origin,x.validation_reason,x.attempt_id,x.prompt_file,x.stream_file,x.context_digest,x.model_digest]),[12,22,95,95,42,75,65,75,75,40,40]);
table('References','凍結參考答案與來源位置',['Question ID','Species','Category','Eligibility','Reference answer','Required elements','Evidence spans','Logical rubric','Arithmetic formula','Human status','Rubric SHA'],refs.map(x=>[x.question_id,x.species,x.category,x.eligibility??x.evidence_verification_level,x.reference_answer,x.required_answer_elements,x.evidence_spans,x.logical_rubric,x.expected_calculation,x.human_review_status,x.rubric_sha256]),[22,12,24,42,75,75,90,85,60,25,40]);
table('Frozen_Settings','設定與重現性',['Item','Value','Source'],[['Run ID',metrics.run_id,'final_run_frozen_manifest.json'],['Corpus SHA','b51b14bfdad0c31a1f64c50d79b511eadf03ce0d55fd8e3d7e59b9a7d350a99e','corpus/marine_hybrid_rag_corpus_v3.sqlite3'],['Frozen at',mf.frozen_at,'final_run_frozen_manifest.json'],['Prompt version',mf.prompt_version,'fair_grounded_rag_final.py'],['Generation options',mf.options,'final_run_frozen_manifest.json'],['Retrieval','BM25 + BGE-M3 + RRF k60 + BGE reranker; at most1 supplemental query','shared_contexts_180.jsonl'],...mids.map(m=>[m,metrics.models[m].tag+' / '+identity.models[m].runtime.details.quantization_level+' / '+identity.models[m].show.model_info['general.architecture']+' / '+metrics.models[m].digest,'model_runtime_identity.json']),['Independent Judge','Mistral NeMo 12B; full digest in Judge raw attempts','judge_raw_attempts.jsonl'],['Human Gold',0,'AUTO_SOURCE_VERIFIED; NOT_HUMAN_GOLD'],['Source dependence','50題 /10 record-page groups /3 files','source_group_evaluation.json'],['Production switch',false,'compatibility.json']], [32,110,75]);
const limits=[['NOT_HUMAN_GOLD','50題由來源核驗及AI輔助判分，沒有人工專家Gold。'],['NOT_INDEPENDENT_HOLDOUT','180題反覆用於來源、Prompt與檢索調整，不能宣稱未曝光Holdout。'],['REFERENCE_INFORMED_RETRIEVAL','已知來源條款優先及凍結證據狀態屬回歸設計；不代表一般問題泛化能力。'],['SOURCE_DEPENDENCY','50題來自10組原始紀錄/PDF頁、3份原件；不能視為50份獨立知識。'],['LIMITED_CATEGORIES','無完整來源支持用藥題；疾病樣本僅2，魚種與計算覆蓋不均。'],['P5_SCOPE','P@5僅12題完全相同Context探索性子集，不能外推180題。'],['MEMORY_SCOPE','RAM/VRAM為每次系統採樣峰值平均，並非模型程序專屬峰值。Shared GPU N/A。'],['ABSTENTION_NOT_TRUTH','其餘130題不是一律應拒答真值，無法計算全體Abstention Correctness。'],['MODEL_SYSTEM_SEPARATION','確定性摘取不計模型成功；原始JSON失敗不能用系統封裝改寫。'],['JUDGE_SCOPE','Faithfulness/Relevance是探索性AI評分，不能當水產專業準確率。'],['ORDER_EFFECT','模型依序執行並暖機；GPU/OS採樣可能受系統背景負載影響。'],['PRECHECK_FAILURE','M3部分支持案例被數值閘安全攔截；保留模型作答失敗而非宣稱全數內容正確。']];
limits.push(['POST_RUN_CONTENT_AUDIT','同一明確結果片語規則核對104筆算術分層紀錄，恢復M1兩筆正確總數的內容判定。凍結引擎原始誤拒與任務成功旗標不變，並非重新生成或更換答案。']);
table('Errors_Limits','錯誤與研究限制',['Type / Model','Question ID','Reason','Detail'],[...limits.map(x=>[x[0],null,x[1],null]),...per.filter(x=>x.validation_reason||!x.raw_schema_valid).map(x=>[x.model_id,x.question_id,x.validation_reason,x.raw_model_response])],[32,22,100,100]);
table('Validation','統計與保護核對',['Check','Actual','Expected','Status'],[['Final unique pairs',valid.unique_final_pairs,720,'VERIFIED'],...Object.entries(valid.model_counts).map(([m,n])=>[m+' final records',n,180,'VERIFIED']),['Same contexts',valid.same_contexts_across_models,true,'VERIFIED'],['Raw attempts',valid.raw_attempt_n,'Every attempt preserved','RECORDED'],['Frozen inputs','All SHA checked','Unchanged','VERIFIED'],['Frozen Manifest',compat.protected_manifest_unchanged,636,'VERIFIED'],['Historical changes',compat.historical_changed_paths.length,0,'VERIFIED'],['Production SQLite',compat.production_sqlite_sha256,'d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087','VERIFIED'],['Full model bytes rehashed',false,false,'NOT_PERFORMED; digest + metadata checked']],[32,80,80,50]);
const ds=sheets.Dashboard;ds.showGridLines=false;ds.tabColor=blue;ds.getRange('A1:S40').format.font={name:font,size:10,color:ink};ds.getRange('A2').values=[['四模型720次固定分母評測']];ds.getRange('A2').format.font={name:font,size:16,bold:true};ds.getRange('A3').values=[['AUTO_SOURCE_VERIFIED · EXPLORATORY · NOT_HUMAN_GOLD']];ds.getRange('A3').format.font={name:font,size:10,italic:true,color:'#6B5B35'};
ds.getRange('A5:G5').values=[['Model','Source50','Logical37','Arithmetic13','Raw JSON180','TTFT s','TPS']];ds.getRange('A5:G5').format={fill:blue,font:{name:font,color:'#FFFFFF',bold:true},rowHeight:32};
for(let i=0;i<4;i++){let r=i+6,fr=i+6;ds.getRange(`A${r}:G${r}`).formulas=[[`='Fixed_Denominators'!A${fr}`,`='Fixed_Denominators'!J${fr}`,`='Fixed_Denominators'!L${fr}`,`='Fixed_Denominators'!N${fr}`,`='Fixed_Denominators'!D${fr}`,`=${mean(mids[i],'ttft_seconds')}`,`=${mean(mids[i],'tps')}`]];}
ds.getRange('B6:E9').setNumberFormat('0.0%');ds.getRange('F6:G9').setNumberFormat('0.000');ds.getRange('A5:G9').format.columnWidth=17;ds.getRange('A5:G9').format.rowHeight=30;
ds.getRange('A12').values=[['主要部署模型建議：'+rec.recommended_primary_deployment_model]];ds.getRange('A12').format.font={name:font,size:14,bold:true};
ds.getRange('A14:G18').values=[['完成生成',metrics.generation_n,'來源核驗題組',metrics.source_qualification_n,'來源組數',source.group_n,null],['Context至少1段',mf.any_context_n,'完整Top-5',mf.full_top5_n,'Human Gold',metrics.human_gold_n,null],['共用P@5平均',metrics.shared_context_precision.mean,'有效題數',metrics.shared_context_precision.n,'範圍','僅12題',null],['Repository pytest',pytest.tests.find(x=>x.name==='repository').counts.passed,'隔離測試',pytest.tests.find(x=>x.name==='isolated').counts.passed,'Frozen Manifest',compat.protected_manifest_unchanged,null],['選型方式','固定50題任務成功率，搭配速度、記憶體與輸出穩定性；無加權總分。',null,null,null,null,null]];
ds.getRange('A20').values=[['限制：重複開發題庫、來源群組集中、無Human Gold；不宣稱統計顯著或專家驗證。']];
ds.getRange('A22').values=[['模型原始表現與確定性摘取分開；任務未成功保留在固定分母，條件式準確率另列。']];
const chart=ds.charts.add('bar',ds.getRange('A5:D9'));chart.title='來源支持題組任務成功率';chart.setPosition('J5','S20');chart.titleTextStyle.typeface=font;chart.titleTextStyle.fontSize=13;chart.legend={position:'top',textStyle:{typeface:font,fontSize:11}};chart.xAxis={axisType:'textAxis',textStyle:{typeface:font,fontSize:11}};chart.yAxis={numberFormatCode:'0%',numberFormatSourceLinked:false,textStyle:{typeface:font,fontSize:11}};chart.series.items.forEach((s,i)=>{s.fill=['#21445F','#547F8B','#BD9855'][i];});
const speed=ds.charts.add('bar',[ds.getRange('A5:A9'),ds.getRange('G5:G9')]);speed.title='實測TPS';speed.setPosition('J22','S36');speed.titleTextStyle.typeface=font;speed.hasLegend=false;speed.yAxis={numberFormatCode:'0.0',numberFormatSourceLinked:false,textStyle:{typeface:font}};speed.series.items[0].fill='#547F8B';
sheets.Frozen_Settings.getRange('B8').values=[[String(mf.frozen_at)+' (Asia/Taipei)']];
wb.recalculate();
// Exercise a genuine formula dependency in memory, then restore the exact input.
// This does not modify any source JSONL or frozen evaluation input.
const validCol=col(fields.indexOf('raw_schema_valid'));
const sample=pdata.findIndex(r=>r[fields.indexOf('model_id')]==='M1'&&r[fields.indexOf('raw_schema_valid')]===1);
const sourceCell=sheets.Per_Question.getRange(`${validCol}${sample+6}`);
const beforeCount=fixed.getRange('C6').values[0][0];
sourceCell.values=[[0]];wb.recalculate();
const changedCount=fixed.getRange('C6').values[0][0];
sourceCell.values=[[1]];wb.recalculate();
const restoredCount=fixed.getRange('C6').values[0][0];
if(changedCount!==beforeCount-1||restoredCount!==beforeCount)throw Error('Formula dependency recalculation did not update/restore');
await fs.writeFile(path.join(W,'workbook_recalculation_test.json'),JSON.stringify({passed:true,beforeCount,changedCount,restoredCount,input_restored:true,source_jsonl_unchanged:true},null,2));
const inspections=[];inspections.push((await wb.inspect({kind:'table',range:'Dashboard!A5:G9',include:'values,formulas',tableMaxRows:5,tableMaxCols:7,maxChars:4500})).ndjson);
inspections.push((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Formula errors'})).ndjson);
await fs.writeFile(path.join(W,'workbook_inspection.txt'),inspections.join('\n'));
await fs.mkdir(path.join(W,'previews'),{recursive:true});
for(const name of names){const blob=await wb.render({sheetName:name,range:name==='Dashboard'?'A1:S37':'A1:H10',scale:1,format:'png'});await fs.writeFile(path.join(W,'previews',name+'.png'),new Uint8Array(await blob.arrayBuffer()));}
const out=await SpreadsheetFile.exportXlsx(wb);await out.save(path.join(W,'fish_test_final_fixed_denominator_evaluation.xlsx'));
await fs.writeFile(path.join(W,'workbook_build_validation.json'),JSON.stringify({created:true,sheets:names,rendered_sheets:names.length,source_record_n:per.length,authoring_engine:'@oai/artifact-tool',recalculated:true,formula_scan:'workbook_inspection.txt',source_data_unchanged:true},null,2));
console.log('Workbook exported; rendered',names.length,'sheets');
