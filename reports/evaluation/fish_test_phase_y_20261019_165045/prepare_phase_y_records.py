import json,pathlib,hashlib,sys,collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT=pathlib.Path.cwd(); E=ROOT/'reports/evaluation'; Y=E/'fish_test_phase_y_20261019_165045'; X=E/'fish_test_phase_x_20261019_162147'; R=E/'fish_test_phase_r_20261017_170144'; W=E/'fish_test_phase_w_20261019_133804'
def rows(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def write_jsonl(p,rs): p.write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rs),encoding='utf-8')
# S08/S10 isolated crosswalk sidecar write-back, preserving unresolved evidence and rights blockers.
proposal=json.loads((R/'source_crosswalk_correction_proposal.json').read_text(encoding='utf-8-sig'))
followups=rows(W/'official_source_followups.jsonl')
entries=[]
for p in proposal['proposals']:
 sid=p['source_id'];
 entry={'error_id':p['error_id'],'source_id':sid,'previous_incorrect_document_id':p['incorrect_document_id'],'previous_incorrect_document_title':p['incorrect_document_title'],'verified_source_identity':p['proposed_identity'],'official_url':p['official_url'],'crosswalk_action':p['proposed_action'],'identity_evidence':p['evidence_locator'],'identity_status':'CONFIRMED_IDENTITY_MISMATCH','source_bytes_saved':False,'source_sha256':None,'content_version_status':'UNVERIFIED','species_or_technical_scope_status':'UNVERIFIED','full_text_indexing_basis':'UNVERIFIED','admission_status':'NOT_ADMITTED','corpus_inclusion_status':'NOT_INGESTED','retrieval_allowlist_status':'EXCLUDED_PENDING_CONTENT_AND_USAGE_REVIEW','writeback_status':'WRITTEN_TO_PHASE_Y_VERSIONED_SIDECAR_ONLY'}
 if sid=='S08':
  entry.update({'service_description':'Fisheries Agency aquaculture stocking quantity query service, not the cold-weather advisory PDF.','schema_or_response_capture':'not captured in prior source review; no stable response/version or raw bytes recorded','content_not_used_as_evidence':True})
 else:
  entry.update({'service_description':'Central Weather Administration Open Data API Swagger documentation page, not a legal explanation document.','official_api_developer_manual':'https://opendata.cwa.gov.tw/devManual/description','manual_observation':'Prior official-page review indicates API service access uses registered member/authentication credentials; this describes API access, not a full-text indexing license.','content_not_used_as_evidence':True,'snapshot_status':'no reproducible HTML bytes or checksum in current source records'})
 entries.append(entry)
writeback={'overlay_version':'phase_y_source_crosswalk_overlay_v1','created_at_local':'2026-10-19','writeback_scope':'isolated Phase Y sidecar; no historical registry, frozen corpus or production metadata edited','proposal_source':'Phase R source_crosswalk_correction_proposal.json','entries':entries,'other_aliases':'not modified; no forced merge without source evidence','automatic_indexing_effect':False,'owner_approval_does_not_establish_third_party_full_text_permission':True}
(Y/'source_crosswalk_writeback.json').write_text(json.dumps(writeback,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Freeze the independently prepared 28 candidate records as a research-only rubric registry.
refs=rows(X/'verified_reference_answer_candidates.jsonl')
freeze=[]
for r in refs:
 out=dict(r)
 out.update({'phase_y_rubric_registry_version':'phase_y_reference_rubrics_v1','rubric_freeze_status':'FROZEN_RESEARCH_ONLY' if r.get('verification_status')=='SOURCE_VERIFIED_AUTOMATED' else r.get('verification_status'),'rubric_freeze_scope':'Derived only from Phase X source spans, candidate answers and deterministic arithmetic records; not Human Gold.','freeze_precedes_accuracy_scoring':True,'human_gold_status':'NOT_HUMAN_GOLD','human_gold_reviewed':False,'new_generator_responses_used_to_author_rubric':False,'source_usage_limit_preserved':r.get('limitations')})
 payload={k:v for k,v in out.items() if k not in ('rubric_sha256','registry_sha256')}
 out['rubric_sha256']=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 freeze.append(out)
write_jsonl(Y/'reference_answer_rubrics_frozen.jsonl',freeze)
# 13 M2 refusal candidates, joined to fixed questions, actual W retrieval context and Phase X source checks.
detail={r['question_id']:r for r in rows(Y/'m2_abstention_detail_180.jsonl')}
retr={r['question_id']:r for r in rows(W/'retrieval_results_v3_updated.jsonl')}
byref={r['question_id']:r for r in refs}
ids=['FT-tilapia-Q12','FT-tilapia-Q17','FT-mullet-Q11','FT-mullet-Q24','FT-mullet-Q25','FT-milkfish-Q01','FT-milkfish-Q04','FT-milkfish-Q05','FT-milkfish-Q11','FT-milkfish-Q12','FT-eel-Q18','FT-seabass-Q03','FT-seabass-Q11']
findings={
'FT-tilapia-Q12':('CONTEXT_DIRECTLY_SUPPORTS_REQUESTED_CORRECTION','寒流時避免投餌、換水在Top-5有直接段落；支援操作修正，不支持額外水溫閾值推論。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-tilapia-Q17':('CONTEXT_DIRECTLY_SUPPORTS_REQUESTED_CORRECTION','Top-5明載魚塭北側及棚蓋角度小於30度；可直接指出南側35度與建議不符。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-mullet-Q11':('CONTEXT_DIRECTLY_SUPPORTS_REQUIRED_AGE_AND_RANGE','Top-5載明烏魚2齡以上建議5,000–6,000尾/公頃並依現場調整；可指出12,000高於該章建議值。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-mullet-Q24':('QUESTION_ONLY_DETERMINISTIC_ARITHMETIC','題幹已給26至28°C，算中點可做算術診斷；Top-5沒有該測值的來源方法，不能算來源支持拒答案例。','NOT_A_SOURCE_GROUNDED_FALSE_REFUSAL'),
'FT-mullet-Q25':('RETRIEVED_CONTEXT_DOES_NOT_MATCH_REQUIRED_MEASURE','題目提供溶氧範圍可作算術診斷，但Top-5是放養密度段落，並未提供或支持溶氧事實。','REFUSAL_JUSTIFIED_FOR_RETRIEVAL_GROUNDED_ANSWER'),
'FT-milkfish-Q01':('CONTEXT_DIRECTLY_SUPPORTS_THRESHOLD_AND_ACTION','Top-5明載低於15°C採緊急措施，例如加溫；14.8°C符合該條件。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-milkfish-Q04':('CONTEXT_DIRECTLY_SUPPORTS_SPECIES_AND_VALUE','Top-5載明虱目魚越冬溝密度每立方公尺1.3公斤以下，且有環境與種類限制。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-milkfish-Q05':('CONTEXT_DIRECTLY_SUPPORTS_ACTION_AND_PURPOSE','Top-5明載撿除浮魚以防水質惡化，可回答處置和來源所述目的。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-milkfish-Q11':('CONTEXT_DIRECTLY_SUPPORTS_OPERATIONAL_CORRECTION','Top-5明載寒流避免投餌、換水及無謂操作，可修正題幹做法。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-milkfish-Q12':('PARTIAL_CONTEXT_SUPPORTS_ACTION_AND_LIMITED_REASON','Top-5支持立即撿除浮魚以防水質惡化；不能據此解釋異味成因。可答支持部分並明確限縮，不宜把異味原因臆測為已知。','PARTIAL_ANSWER_SUPPORTED'),
'FT-eel-Q18':('LAW_CONTEXT_RELEVANT_BUT_NOT_DISPOSITIVE','Top-5有一般用藥依法規及禁藥/殘留規則；沒有直接建立所有歷史放養資料與現行法規衝突的優先規則。需具體法規範圍或問題澄清。','NOT_CONFIRMED_AS_UNNECESSARY_REFUSAL'),
'FT-seabass-Q03':('CONTEXT_DIRECTLY_SUPPORTS_SPECIFIC_SUBSPECIES_COMPARISON','Top-5明載金目鱸養殖池5 psu以上較佳；問題明確指金目鱸，4 psu可描述為低於該手冊建議。不得泛化到所有鱸魚。','ANSWERABLE_FROM_RETRIEVED_FACT_CARD'),
'FT-seabass-Q11':('CONTEXT_DIRECTLY_SUPPORTS_LIMITED_TEMPERATURE_RESPONSE','Top-5明載金目鱸低於23°C食慾降低；21.5°C低於該值。可作有條件解讀，不診斷水黴感染。','ANSWERABLE_WITH_EXPLICIT_LIMITATION')}
records=[]
for qid in ids:
 d=detail[qid]; rr=retr[qid]; rf=byref.get(qid); kind,reason,status=findings[qid]
 records.append({'question_id':qid,'species':rr.get('species'),'category':rr.get('category'),'question_text':rr.get('question_text'),'phase_w_m2_abstention':d,'retrieval_contexts':rr.get('reranked_top5',[]),'reference_candidate':rf,'content_evidence_diagnosis':kind,'diagnosis_reason':reason,'assessment':status,'evidence_sufficiency_before_model':d.get('evidence_sufficiency'),'model_self_abstention_reason':d.get('abstention_reason'),'source_usage_basis_status':(rf or {}).get('source_usage_basis') or 'No verified answer source record linked in prior candidate registry','not_human_gold':True,'limitations':['This is a source/context audit of 13 flagged candidates, not a full-run causal intervention or accuracy estimate.','Source evidence cards do not imply blanket permission for full-text indexing.']})
write_jsonl(Y/'m2_abstention_regression.jsonl',records)
print(json.dumps({'rubric_rows':len(freeze),'rubric_source_verified':sum(r.get('verification_status')=='SOURCE_VERIFIED_AUTOMATED' for r in freeze),'rubric_arithmetic_diagnostic':sum(r.get('verification_status')=='ARITHMETIC_DIAGNOSTIC_ONLY' for r in freeze),'rubric_not_evaluable':sum(r.get('verification_status')=='NOT_EVALUABLE' for r in freeze),'m2_candidate_rows':len(records),'m2_assessment_counts':dict(collections.Counter(r['assessment'] for r in records))},ensure_ascii=False,indent=2))
