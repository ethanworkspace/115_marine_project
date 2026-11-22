"""Explicit 70/30 exploratory model selection, without changing frozen runs."""
import collections,copy,datetime,hashlib,json,math,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1];SOURCE=ROOT/'reports/evaluation/unified_rag_v6_evaluation_20261121_164940'
def read(n):return json.loads((SOURCE/n).read_text(encoding='utf-8'))
def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
def dump(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    qc=read('evaluation_metrics_11_source_qc.json');paired=read('paired_sample_comparison.json');identity=read('model_runtime_identity.json');models=list(qc['models']);now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)));out=ROOT/'reports/evaluation'/('unified_rag_v6_weighted_selection_'+now.strftime('%Y%m%d_%H%M%S'));out.mkdir()
    defs=[('faithfulness','Faithfulness','quality',.175,'higher','bounded','model_faithfulness'),('bge_relevance','BGE-M3 relevance','quality',.175,'higher','bounded','model_bge_cosine'),('logical_task_success','Logical fixed task success','quality',.175*37/50,'higher','bounded',None),('arithmetic_task_success','Arithmetic fixed task success','quality',.175*13/50,'higher','bounded',None),('structured_ifr','Raw structured IFR','quality',.175,'higher','bounded',None),('ttft','Visible-content TTFT','performance',.10,'lower','min_over_value','ttft_seconds'),('tps','Engine TPS','performance',.10,'higher','value_over_max','tps'),('ram','Sampled system RAM efficiency','performance',.05,'lower','min_over_value','peak_system_ram_gib'),('vram','Sampled device VRAM efficiency','performance',.05,'lower','min_over_value','peak_dedicated_vram_gib'),('judge_relevance','Judge Answer Relevance diagnostic','diagnostic',0.,'higher','bounded','model_judge_relevance'),('context_precision','Shared exploratory P@5','diagnostic',0.,'higher','bounded',None)]
    assert math.isclose(sum(d[3] for d in defs),1) and math.isclose(sum(d[3] for d in defs if d[2]=='quality'),.7) and math.isclose(sum(d[3] for d in defs if d[2]=='performance'),.3)
    raw={};ns={};content={}
    for m,v in qc['models'].items():
        z=v['layers']['model'];raw[m]={};ns[m]={};content[m]={}
        for key,label,group,weight,direction,mode,pkey in defs:
            if pkey:raw[m][key]=paired[pkey]['models'][m]['mean'];ns[m][key]=paired[pkey]['common_n']
            elif key=='logical_task_success':raw[m][key]=z['logical_accuracy']['fixed_validated_success']['rate'];ns[m][key]=37
            elif key=='arithmetic_task_success':raw[m][key]=z['arithmetic_accuracy']['fixed_validated_success']['rate'];ns[m][key]=13
            elif key=='structured_ifr':raw[m][key]=v['raw_schema']['rate'];ns[m][key]=180
            elif key=='context_precision':raw[m][key]=qc['shared_context_precision']['mean'];ns[m][key]=qc['shared_context_precision']['n_questions']
            content[m]['logical_task_success']=z['logical_accuracy']['fixed_content_success']['rate'];content[m]['arithmetic_task_success']=z['arithmetic_accuracy']['fixed_content_success']['rate']
    for m in models:
        assert all(x is not None and math.isfinite(x) for x in raw[m].values())
    def evaluate(variant='primary',quality_weight=.7):
        weights={d[0]:d[3] for d in defs};values=copy.deepcopy(raw)
        if variant=='content_criterion':
            for m in models:values[m].update(content[m])
        if variant=='memory_excluded':weights.update(ram=0.,vram=0.,ttft=.15,tps=.15)
        detail=[];ranking=[]
        for m in models:
            q=e=0.
            for key,label,group,weight,direction,mode,pkey in defs:
                v=values[m][key];cohort=[values[t][key] for t in models];w=weights[key]
                if variant=='minmax_performance' and group=='performance':
                    span=max(cohort)-min(cohort);s=((max(cohort)-v) if direction=='lower' else (v-min(cohort)))/span if span else 1.
                elif mode=='bounded':s=max(0.,min(1.,v))
                elif mode=='min_over_value':assert v>0;s=min(cohort)/v
                else:assert max(cohort)>0;s=v/max(cohort)
                w=w*(quality_weight/.7 if group=='quality' else (1-quality_weight)/.3 if group=='performance' else 1)
                assert 0<=s<=1 and w>=0;points=100*w*s
                q+=points if group=='quality' else 0;e+=points if group=='performance' else 0
                detail.append({'model_id':m,'metric_id':key,'metric':label,'group':group,'weight':w,'raw_value':v,'valid_n':ns[m][key],'direction':direction,'normalization':('minmax_cohort' if variant=='minmax_performance' and group=='performance' else mode),'cohort_best':min(cohort) if direction=='lower' else max(cohort),'normalized_score':s,'weighted_points':points})
            ranking.append({'model_id':m,'tag':identity[m]['tag'],'digest':identity[m]['digest'],'quality_points_out_of_70':q,'performance_points_out_of_30':e,'total_out_of_100':q+e,'quality_mean_score':q/(100*quality_weight) if quality_weight else None,'performance_mean_score':e/(100*(1-quality_weight)) if quality_weight<1 else None})
        ranking.sort(key=lambda r:r['total_out_of_100'],reverse=True)
        for rank,r in enumerate(ranking,1):r['rank']=rank
        return {'variant':variant,'quality_weight':quality_weight,'performance_weight':1-quality_weight,'ranking':ranking,'metric_contributions':detail,'winner':ranking[0]['model_id']}
    primary=evaluate();sensitivity=[evaluate(v) for v in ('content_criterion','memory_excluded','minmax_performance')];sweep=[{'quality_weight':q,'performance_weight':1-q,'winner':(r:=evaluate('primary',q))['winner'],'scores':{x['model_id']:x['total_out_of_100'] for x in r['ranking']}} for q in (.5,.6,.7,.8,.9,.95,1.)]
    policy={'version':'v6-weighted-selection-70-30-20261122-v1','status':'EXPLORATORY_SELECTION_NOT_PRE_REGISTERED_FORMAL_BENCHMARK','user_approved_parent_weights':{'quality':.70,'performance':.30,'approval_source':'Current user explicitly selected 沿用品質70%、效能30%（建議）'},'subweights_and_mapping':defs,'assumptions_not_misrepresented_as_original_approval':['Historical memory-pressure and TTFT/TPS score bounds were not located; these are explicit current-selection mappings, not a recovered approved original formula.','The historical 10% memory item is provisionally split equally into RAM and VRAM efficiency (5% each). These are whole-system/device sampled proxies, not model-process pressure.','The historical 17.5% Logical/Arithmetic item is pooled across fixed 37+13 source-qualified tasks; weights 12.95% and 4.55% give each of the 50 tasks equal credit.','Primary success requires frozen-source content plus original format/source/citation program checks. A content-only sensitivity analysis separately exposes known gate false negatives.'],'formula':'100 * [0.175*F + 0.175*BGE + 0.1295*LogicalTask37 + 0.0455*ArithmeticTask13 + 0.175*RawIFR + 0.10*TTFTscore + 0.10*TPSscore + 0.05*RAMscore + 0.05*VRAMscore]','normalization':{'higher_quality':'Original bounded 0..1; cosine uses max(0,min(1,cosine)), not four-model minmax. Actual cohort cosines are positive.','ttft_ram_vram':'Best (lowest) paired cohort mean / model paired cohort mean','tps':'Model paired cohort mean / best (highest) paired cohort mean','direction':'Higher normalized score is better for every term','cohort_dependency':'Scores depend on this four-model cohort and machine; not transferable universal percentages.'},'judge_relevance_weight':0,'judge_relevance_reason':'Retained independently; original relevance requirement is BGE-M3, so do not blend two relevance measures or double count.','context_precision_weight':0,'context_precision_reason':'Shared retrieval, fixed exploratory 12-question sample; cannot distinguish model quality.','missing_values':'No N/A filled with zero. TTFT uses the same 179 nonmissing questions for all four models; other continuous metrics use paired common samples. Fixed-task non-success follows the pre-existing denominator rule.','old_double_weighting_removed':True,'theoretical_max_score':100,'actual_source_human_gold':0,'sample_limits':'50 source-qualified questions, 10 source groups, 3 original files; AI source QA, not expert truth or unseen holdout','no_production_switch':True}
    inputs=['evaluation_metrics_11_source_qc.json','paired_sample_comparison.json','model_runtime_identity.json','result_artifact_manifest.json','metric_spec_v6.json'];input_manifest=[{'path':str(SOURCE/n),'sha256':sha(SOURCE/n)} for n in inputs]
    result={'created_at':now.isoformat(),'source_run':SOURCE.name,'policy':policy,'primary':primary,'sensitivity':sensitivity,'quality_share_sweep':sweep,'same_top_model_in_declared_70_30_sensitivity':all(x['winner']==primary['winner'] for x in sensitivity),'inputs':input_manifest,'historical_files_overwritten':False,'no_new_inference':True}
    dump(out/'weighted_model_selection.json',result);dump(out/'weighted_scoring_policy.json',policy);dump(out/'weighted_input_manifest.json',input_manifest)
    lines=['# 綜合加權模型選型',f'來源：{SOURCE.name}；本次只讀既有720次推論，不重跑模型、不更動Corpus或歷史結果。','',f'**依使用者選定的品質70%／效能30%，本輪加權第一名為{primary["winner"]}。**','', '## 權重與正規化','', '| 項目 | 權重 | 取值方式 |','|---|---:|---|','| Faithfulness |17.5%|四模型共同有效35題|','| BGE-M3 Relevance |17.5%|四模型共同有效37題|','| Logical任務成功 |12.95%|Source QA後、內容與原始輸出驗證皆通過／固定37題|','| Arithmetic任務成功 |4.55%|內容與原始輸出驗證皆通過／固定13題|','| 原始JSON IFR |17.5%|格式通過／180題|','| TTFT |10%|共同有效179題；最小平均值／各模型平均值|','| TPS |10%|共同180題；各模型平均值／最大平均值|','| RAM效率代理 |5%|共同180題；最小系統採樣峰值平均／各模型值|','| VRAM效率代理 |5%|共同180題；最小設備採樣峰值平均／各模型值|','', 'Judge Relevance保留診斷、權重0；P@5為共用檢索指標、權重0。所有貢獻只乘一次最終權重，不再次乘70%／30%，理論滿分100。','', '**70/30已由使用者確認；記憶體拆分及相對正規化是本輪明列的選型假設。原文件未找到完整效能／Memory Pressure正規化定義，因此不能稱為原論文已正式凍結的總分。**','', '## 加權結果','', '| 名次 | 模型 | 品質貢獻／70 | 效能貢獻／30 | 總分／100 |','|---|---|---:|---:|---:|']
    for r in primary['ranking']:lines.append(f'|{r["rank"]}|{r["model_id"]}：{r["tag"]}|{r["quality_points_out_of_70"]:.2f}|{r["performance_points_out_of_30"]:.2f}|{r["total_out_of_100"]:.2f}|')
    lines+=['', '## 敏感度檢查','', '| 相同資料的計分檢查 | 第一名 |','|---|---|']
    for s in sensitivity:lines.append('| '+{'content_criterion':'準確性改用來源內容符合，不受已知驗證閘誤拒影響','memory_excluded':'移除未核定記憶體代理；效能30%改由TTFT/TPS各15%','minmax_performance':'效能改用本批min-max正規化'}[s['variant']]+' | '+s['winner']+' |')
    lines+=['', '這些是同一凍結結果的計分敏感度，不是新增RAG版本、A/B或消融實驗。完整權重敏感度與逐項加權點數見JSON。', '', '## 判讀', '', 'M2為本輪70/30方案的首選，兼顧互動延遲、輸出穩定與資源效率。M4的50題內容符合率仍最高，但在現有硬體的生成速度與資源代理項目較不利；加權第一不代表M2專業內容符合率最高。', '', '分數是公開假設下的相對選型分，不是答對率、統計顯著性或專家認證。RAM／VRAM不是模型程序專屬用量；TPS可能受tokenizer與推理token影響；TTFT不包含預先凍結的檢索時間。Human Gold為0，來源群組集中，且仍有AI來源QA待複核案例。沒有自動切換Production。', '', '## 重現性', '', '逐項原值、有效N、正規化方式、權重與加權點數已保存在weighted_model_selection.json；輸入SHA見weighted_input_manifest.json。']
    (out/'weighted_model_selection_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump(ROOT/'research_staging/unified_rag_v6_weighted_selection_pointer.json',{'directory':str(out)})
    print(json.dumps({'directory':str(out),'ranking':primary['ranking'],'sensitivity_winners':{x['variant']:x['winner'] for x in sensitivity},'quality_sweep':sweep},ensure_ascii=False))

if __name__=='__main__':main()
