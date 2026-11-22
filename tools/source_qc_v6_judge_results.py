"""Source-based post-run QC; preserve frozen Judge outputs and rubric bytes."""
import collections,copy,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev
from summarize_unified_rag_v6 import accuracy,rate,write_jsonl

def main():
    w=ev.work();ev.verify_freeze(w,True);base=ev.read(w/'evaluation_metrics_11.json');refs={r['question_id']:r for r in ev.jl(w/'verified_reference_answers_v6.jsonl')};original=ev.jl(w/'logical_accuracy_detailed.jsonl');arithmetic=ev.jl(w/'arithmetic_accuracy_detailed.jsonl');warned=ev.jl(w/'judge_species_wording_review.jsonl')
    decisions={('FT-seabass-Q02','M1'):('incorrect','WRONG_REQUIRED_DISEASE_NAME','原文明示水黴病二次感染，模型兩次改為水白菜／水白菜病；必答疾病資訊錯誤，不是可接受同義表述。'),('FT-seabass-Q11','M4'):('not_evaluable','INCOMPLETE_REQUIRED_RISK_CONCLUSION','只描述低溫與攝食下降，未給凍結必要的水黴風險，並逕稱正常生理反應；完整必答結論未形成。保守列不可完整判定，固定任務仍不成功，不把不完整直接等同數值錯誤。')}
    index={(r['question_id'],r['model_id'],r['answer_layer']):r for r in original};reviews=[];seen=set()
    for warning in warned:
        pair=warning['question_id'],warning['model_id']
        if pair in seen:continue
        seen.add(pair);r=index[(*pair,'model')];ref=refs[pair[0]]
        status='CORE_SOURCE_CONCLUSION_CORROBORATED_JUDGE_TRANSLATION_WRONG';reason='原始中文回答的金目鱸及核心數值可依凍結來源核對；Judge英文goldfish是誤譯，不能當作金魚適用依據。'
        if pair in decisions:status=decisions[pair][1];reason=decisions[pair][2]
        elif pair==('FT-seabass-Q03','M1'):status='REQUIRES_REVIEW_EXTRA_CAUSAL_CLAIMS';reason='4 psu與5 psu的核心比較存在，但附加疾病復發與生產效益因果主張尚未由本次凍結引文完整核實；保留原判及疑義，不自動認證額外主張。'
        elif pair==('FT-seabass-Q01','M3'):status='REQUIRES_REVIEW_EXTRA_APPLICABILITY';reason='28–32°C核心範圍有來源，但附加浮筏光電的物種與場域適用性未在此凍結引文中核實；保留原判並待複核。'
        elif pair==('FT-seabass-Q03','M3'):status='ORIGINAL_NOT_EVALUABLE_RETAINED';reason='只重述建議5 psu且宣稱缺條件，未完整比較題目的4 psu，保留原not_evaluable。'
        reviews.append({'question_id':pair[0],'model_id':pair[1],'question':ref['original_question'],'raw_answer':r['raw_answer_text'],'original_verdict':r['verdict'],'qc_verdict':decisions[pair][0] if pair in decisions else r['verdict'],'qc_status':status,'reason':reason,'required_answer_elements':ref['required_answer_elements'],'frozen_rubric_sha256':ref['rubric_sha256'],'exact_source_evidence':ref['evidence_spans'],'v6_original_quote_checks':ref['v6_reference_checks'],'original_judge_scores':r.get('evaluation',{}).get('scores'),'reviewer_type':'CODEX_SOURCE_ALIGNMENT_REVIEW','verification_level':'AI_ASSISTED_POST_RUN_QC_NOT_HUMAN_GOLD','reference_answer_or_rubric_changed':False,'all_other_cases_not_claimed_independently_reviewed':True})
    updated=[];changes=[]
    for r in original:
        item=copy.deepcopy(r);pair=r['question_id'],r['model_id'];item['original_frozen_judge_verdict']=r['verdict']
        if pair in decisions:
            assert r['verdict']=='correct';verdict,code,why=decisions[pair];item.update(verdict=verdict,reason=why,content_task_success=False,validated_task_success=False,post_run_source_qc_status=code,post_run_source_qc_level='AI_ASSISTED_NOT_HUMAN_GOLD');changes.append(item)
        updated.append(item)
    assert len(changes)==4 and len(reviews)==9
    write_jsonl(w/'logical_accuracy_source_qc_detailed.jsonl',updated);write_jsonl(w/'source_qc_judge_review_9.jsonl',reviews)
    corrected=copy.deepcopy(base)
    for model,v in corrected['models'].items():
        for layer in ('model','system'):
            lr=[r for r in updated if r['model_id']==model and r['answer_layer']==layer];ar=[r for r in arithmetic if r['model_id']==model and r['answer_layer']==layer];z=v['layers'][layer];z['logical_accuracy']=accuracy(lr,base['fixed_reference_policy']['fixed_logical_n']);z['source_50_task_success']=rate(r['validated_task_success'] for r in lr+ar);z['source_50_content_correct_rate']=rate(r['content_task_success'] for r in lr+ar)
    corrected['post_run_source_qc']={'at':ev.now(),'original_metrics_sha256':ev.sha(w/'evaluation_metrics_11.json'),'original_logical_rows_sha256':ev.sha(w/'logical_accuracy_detailed.jsonl'),'affected_question_model_pairs':2,'changed_layer_records':4,'reviewed_warning_pairs':9,'method':'Direct original-question, frozen required-element and exact-source comparison; no new Generator or Judge inference; no reference or rubric revision','limits':'Only identified discrepancies corrected; other AI judgments are not expert verified. Two extra-claim cases remain flagged. Human Gold remains 0.'}
    ev.dump(w/'evaluation_metrics_11_source_qc.json',corrected)
    old=ev.read(w/'paired_sample_comparison.json');paired={};pol=base['fixed_reference_policy']
    for layer in ('model','system'):
        idx={(r['question_id'],r['model_id']):r for r in updated if r['answer_layer']==layer};ids=[q for q in pol['logical_question_ids'] if all(idx[q,m]['verdict'] in ('correct','incorrect') for m in ev.MODEL_SPECS)];paired[layer]={'common_n':len(ids),'question_ids':ids,'models':{m:accuracy([idx[q,m] for q in ids],len(ids)) for m in ev.MODEL_SPECS},'scope':'SOURCE_QC_EXPLORATORY_NOT_HUMAN_GOLD'}
    ev.dump(w/'paired_logical_source_qc.json',paired)
    marker='\n## 最終來源QA（與原始評分分開）\n';report=(w/'final_720_evaluation_report.md').read_text(encoding='utf-8').split(marker)[0]
    lines=[marker,'查出Judge將金目鱸誤稱goldfish，包含Carassius auratus的錯誤學名；9組題目／模型警示均另留原文核對。這不是Human Gold。依凍結前的必要答案元素，M1 FT-seabass-Q02把水黴寫成水白菜，correct改為incorrect；M4 FT-seabass-Q11漏掉必要水黴風險，correct保守改為not_evaluable。模型與系統層共4列修正，原始JSONL與原始11項統計完全保留。', '', '| 來源QA修正版（非Human Gold） | M1 | M2 | M3 | M4 |','|---|---:|---:|---:|---:|']
    for title,key in [('Logical條件式準確率','logic'),('50題內容符合','content'),('50題內容＋程式閘成功','validated')]:
        vals=[]
        for m in ev.MODEL_SPECS:
            z=corrected['models'][m]['layers']['model'];a=z['logical_accuracy']
            vals.append(f'{a["correct_n"]}/{a["conditional_n"]} ({a["conditional_accuracy"]:.2%})' if key=='logic' else f'{(r:=z["source_50_content_correct_rate" if key=="content" else "source_50_task_success"])["success_n"]}/{r["n"]} ({r["rate"]:.2%})')
        lines.append('| '+title+' | '+' | '.join(vals)+' |')
    lines+=['','其他9項及Arithmetic原始計分未變。來源QA不是對全部標籤的獨立專家複核；M1 FT-seabass-Q03與M3 FT-seabass-Q01的額外因果／適用性主張仍列待查。這些限制阻止將Logical指標宣稱為正式專業準確率。原始AI分數見Model_Comparison，修正版與逐筆理由見Source_QC及新增JSON。']
    (w/'final_720_evaluation_report.md').write_text(report+'\n'.join(lines)+'\n',encoding='utf-8');ev.verify_freeze(w,True);ev.emit(corrected['post_run_source_qc'])

if __name__=='__main__':main()
