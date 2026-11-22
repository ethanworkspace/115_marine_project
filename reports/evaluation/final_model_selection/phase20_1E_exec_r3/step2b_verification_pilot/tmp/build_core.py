import json, hashlib, pathlib, re
import pymupdf
R=pathlib.Path(r'C:\my project\115_marine_project')
S=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2_existing_corpus'
O=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2b_verification_pilot'
def j(p): return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
def wj(n,x): (O/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def wl(n,x): (O/n).write_text(''.join(json.dumps(a,ensure_ascii=False,separators=(',',':'))+'\n' for a in x),encoding='utf-8')
def hf(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def hb(b): return hashlib.sha256(b).hexdigest()
def norm(s): return re.sub(r'\s+','',s or '')
def catlabel(s): return {'fact':'Fact','water_quality':'Water Quality','disease':'Disease','climate':'Climate / Cold','calculation':'Calculation','medication_law':'Safe Medication / Law'}.get(s,s)
scr=j(S/'screening_processing_report.json'); base=j(S/'existing_corpus_evidence_matrix.json'); gaps=j(S/'targeted_gap_registry.json'); ready2=j(S/'readiness_after_step2.json')
assert scr['candidate_counts']['normal_screening_chunks_processed']==486
assert scr['candidate_counts']['pool_processing_status_counts']=={'needs_review':317,'rejected':169}
assert len(base['cells'])==36 and sum(x['screened_count']==0 for x in base['cells'])==8
assert not (S/'evidence_units_v1.jsonl').read_text(encoding='utf-8').strip()
pool={x['chunk_id']:x for x in map(json.loads,(R/'data/evaluation/grounded/evidence_pool_v1.jsonl').read_text(encoding='utf-8').splitlines())}
corp={x['chunk_id']:x for x in map(json.loads,(R/'data/evaluation/corpus_v2.jsonl').read_text(encoding='utf-8').splitlines())}
proc={x['candidate_id']:x for x in scr['per_candidate']}; gapby={(x['species'],x['category']):x for x in gaps['cells']}
specs=[
('chunk_9ce80c7d6737558c8dfc7b188ac72513',None,'Original journal PDF absent; source verification pending, so Corpus excerpt cannot establish source/page/checksum support.'),
('chunk_be88525e65be5ca3b0df97a392ae74f5',None,'Original journal PDF absent and source verification pending; not promoted from Corpus excerpt alone.'),
('chunk_b0a6b969645558b79a3dd0281d99f144',None,'Original source file absent and source verification pending; cold-effect excerpt cannot be checked against source/version.'),
('chunk_8aa150216d8651cca9ffbf883102e2ff','不受污染之場地','Exact source-page support; distinct mullet site-selection proposition.'),
('chunk_c198c6516b725316b349248ccd7de814','夏天高溫時期，烏魚攝食狀況會降低，故需留意投餵時間以及投餵量，以免殘餌汙染水質誘發疾病的發生。','Exact source-page support for the full conditional proposition, including the disease consequence.'),
('chunk_7dcf98ca3cda581eb1629cc5cc8a1442','冬季或氣候不佳時，可減少投\n餵頻率','Direct grouper feeding statement; line break normalized for PDF check.'),
('chunk_2dae6e21944154a29147711b32516f91','成魚養殖池水深建議至少2 公尺以深','Direct statement in grouper culture section.'),
('chunk_358b2b00decc5ce68ad10d931fc2c288','ORP 在養殖期間均維持在正電位','Direct statement scoped to Tainan Xuejia grouper trial.'),
('chunk_df83bf2bb32f51e48bbf3f67b2f3c9d1',None,'Official-source candidate is shorter than existing quality gate; original source file absent for page/species verification.'),
('chunk_37506175731a52cfa5e884e29bef8cc3',None,'Disease excerpt covers multiple fish groups; source pending and no source PDF, so eel-specific support is unconfirmed.'),
('chunk_22b9e2d6b62b584ba72d5ca49b776c61',None,'Text identifies Japanese eel, but original source PDF is absent and source verification is pending.'),
('chunk_72fbed1cd9645a9bb3b820731edf6c08','魚蛭感染症(Leech infection)\n病原\n臺灣常見魚蛭屬Piscicola sp.','Exact disease heading/pathogen line in verified official handbook; only this narrow proposition is promoted.'),
('chunk_adf0bebfc2c45ef29d6553130ddc1a54',None,'Fact mapping conflicts with temperature/climate proposition; retain for taxonomy review, no silent reclassification.'),
('chunk_094d0f7c030350cf9a57f9fa83b68d9b','建議維持鹽度在5 psu 以上較佳','Exact page text supports golden seabass site/salinity recommendation.')]
pdfs={'a26364f19971d2c98b37f924e680a4664aa7a9887b195e372f486ca3088aeee9':R/'data/recovery/raw_sources/tfrin_technical_manual_17_lower_full.pdf','274288d003984b010e445d6d37018c8405d2238c0e1a622ae029a69161fbf0e1':R/'data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf'}
docs={}
for d,p in pdfs.items():
 if hf(p)!=d: raise RuntimeError('Source PDF checksum mismatch: '+str(p))
 docs[d]=(str(p),pymupdf.open(p))
claims={
'chunk_8aa150216d8651cca9ffbf883102e2ff':'烏魚養殖場址應選擇不受污染的地點。','chunk_c198c6516b725316b349248ccd7de814':'烏魚夏季高溫時應留意投餵時間與餵量，以免殘餌污染水質並誘發疾病。',
'chunk_7dcf98ca3cda581eb1629cc5cc8a1442':'鞍帶石斑在冬季或氣候不佳時可減少投餵頻率。','chunk_2dae6e21944154a29147711b32516f91':'鞍帶石斑成魚養殖池建議水深至少 2 公尺。',
'chunk_358b2b00decc5ce68ad10d931fc2c288':'手冊記載的臺南學甲鞍帶石斑試驗中，養殖期間 ORP 維持正電位。','chunk_72fbed1cd9645a9bb3b820731edf6c08':'金目鱸魚蛭感染症的病原列為臺灣常見魚蛭屬 Piscicola sp.。',
'chunk_094d0f7c030350cf9a57f9fa83b68d9b':'金目鱸養殖區位建議維持鹽度在 5 psu 以上。'}
app={
'chunk_8aa150216d8651cca9ffbf883102e2ff':'烏魚 specific; source section identifies 烏魚','chunk_c198c6516b725316b349248ccd7de814':'烏魚 specific; source section identifies 烏魚',
'chunk_7dcf98ca3cda581eb1629cc5cc8a1442':'鞍帶石斑 specific; source section identifies 鞍帶石斑','chunk_2dae6e21944154a29147711b32516f91':'鞍帶石斑 specific; source section identifies 鞍帶石斑',
'chunk_358b2b00decc5ce68ad10d931fc2c288':'Tainan Xuejia 鞍帶石斑 trial only','chunk_72fbed1cd9645a9bb3b820731edf6c08':'金目鱸 specific as stated in handbook','chunk_094d0f7c030350cf9a57f9fa83b68d9b':'金目鱸 specific as stated in manual'}
candidates=[]; decisions=[]; promoted=[]
for cid,span,why in specs:
 p=pool[cid]; c=corp[cid]; q=proc[cid]
 if p['document_id']!=c['document_id'] or p['content_checksum']!=c['content_checksum'] or hb(p['text'].encode())!=p['content_checksum']: raise RuntimeError('Chunk provenance/checksum mismatch '+cid)
 good=span is not None; pdfpath=None; pdfsha=None; pageok=None; start=end=None
 if good:
  if c.get('ingestion_status') not in (None,'accepted') or p.get('evidence_quality_status')!='accepted': raise RuntimeError('Quality gate not accepted '+cid)
  pdfsha=p['source_checksum']; pdfpath,doc=docs[pdfsha]; page=int(p['page'] or p['pages'][0]); pageok=norm(span) in norm(doc[page-1].get_text())
  if not pageok or not p.get('source_verified') or p.get('source_verification_status')!='verified': raise RuntimeError('Source span or source status failed '+cid)
  if span in p['text']: start=p['text'].find(span); end=start+len(span)
  elif norm(span) not in norm(p['text']): raise RuntimeError('Span absent from candidate chunk '+cid)
 candidates.append({'candidate_id':cid,'original_id':q['original_id'],'original_screening_status':q['original_screening_status'],'step2_status':q['candidate_processing_status'],'step2_reasons':q['reasons'],
 'species':p['species'],'category':p['category'],'risk_level':p['risk_level'],'document_id':p['document_id'],'chunk_id':p['chunk_id'],'page':p['page'],'pages':p['pages'],'source_title':p['document_title'],
 'source_checksum_expected':p['source_checksum'],'content_checksum':p['content_checksum'],'source_verified_step2':p['source_verified'],'source_verification_status_step2':p['source_verification_status'],
 'evidence_quality_status':p['evidence_quality_status'],'warnings':p['warnings'],'quality_reasons':p['quality_reasons'],'support_span':span,'source_pdf_path':pdfpath,'source_pdf_sha256':pdfsha,
 'pilot_status':'silver_ready' if good else 'needs_review','decision_reason':why})
 decisions.append({'candidate_id':cid,'readiness_status':'silver_ready' if good else 'needs_review','evidence_unit_created':good,'document_chunk_page_verified':True,'source_title':p['document_title'],
 'source_checksum_verified':bool(good and hf(pdfpath)==p['source_checksum']),'chunk_text_checksum_verified':True,'support_span':span,'support_start':start,'support_end':end,'source_page_support_match':pageok,
 'quality_gate':p.get('evidence_quality_status'),'atomic_fact':claims.get(cid),'species_applicability':app.get(cid),'duplicate_check':'unique pilot proposition' if good else 'not counted as ready unit',
 'verification_method':'Original PDF checksum + exact/whitespace-normalized cited-page span + Corpus provenance/text checksum + direct source/category/species review.' if good else 'Corpus row and screening metadata inspected; original source not independently verifiable or taxonomy remains unresolved.',
 'reason':why,'human_reviewed':False,'human_gold_claimed':False})
 if good:
  fp=hb('|'.join([p['species'],p['category'],norm(claims[cid]),p['source_checksum']]).encode())[:16]
  promoted.append({'evidence_unit_id':'eu_step2b_'+cid.removeprefix('chunk_'),'species':p['species'],'category':catlabel(p['category']),'risk_level':'normal','atomic_fact_or_rule':claims[cid],
   'support_span':span,'support_start':start,'support_end':end,'chunk_id':cid,'document_id':p['document_id'],'page':p['page'],'source_title':p['document_title'],
   'source_authority':'Fisheries Research Institute source as identified by the frozen source record','source_status':'verified_local_source_pdf_and_page_text','source_version':None,
   'checksum':{'chunk_text_sha256':p['content_checksum'],'source_pdf_sha256':p['source_checksum']},'applicability':app[cid],'duplicate_group_id':'fact_'+fp,
   'readiness_status':'silver_ready','verification_method':'Source PDF SHA-256, cited-page span, Corpus provenance/checksum, accepted quality gate, atomic fact, category and species applicability.',
   'human_reviewed':False,'notes':'Corpus-Grounded Silver; not Human Gold. Proposition remains source-scoped.'})
if len({x['duplicate_group_id'] for x in promoted})!=len(promoted): raise RuntimeError('Duplicate fact fingerprint collision')
review={}; silver={}
for d in decisions:
 p=pool[d['candidate_id']]; k=(p['species'],catlabel(p['category'])); review[k]=review.get(k,0)+1
 if d['readiness_status']=='silver_ready': silver[k]=silver.get(k,0)+1
matrix=[]; remain=[]
for b in base['cells']:
 k=(b['species'],b['category']); g=gapby.get(k,{})
 if b['screened_count']==0: sg={'status':'no_screened_candidate','detail':'No Step2 candidate; targeted search remains necessary. Structural infeasibility not assessed.'}
 elif silver.get(k): sg={'status':'existing_corpus_partial','detail':'Pilot verified source-backed unit(s), but five distinct units are still required.'}
 elif review.get(k): sg={'status':'verification_blocked','detail':next(d['reason'] for d in decisions if (pool[d['candidate_id']]['species'],catlabel(pool[d['candidate_id']]['category']))==k and d['readiness_status']=='needs_review')}
 else: sg={'status':g.get('missing_knowledge_type',b.get('gap_classification','not_promoted')),'detail':b.get('gap_detail') or g.get('missing_knowledge_type')}
 nrem=max(0,int(b.get('needs_review_count',0))-silver.get(k,0)); nready=int(b.get('silver_ready_count',0))+int(b.get('verified_ready_count',0))+silver.get(k,0)
 row={'species':b['species'],'category':b['category'],'target_count':5,'original_screened_count':int(b['screened_count']),'pilot_reviewed_count':review.get(k,0),
 'new_silver_ready_count':silver.get(k,0),'new_verified_ready_count':0,'remaining_needs_review':nrem,'rejected_after_verification':0,'source_gap':sg,
 'shortfall_to_five':max(0,5-nready),'candidate_assignments_are_not_distinct_units':True,'structurally_infeasible':False}
 matrix.append(row)
 remain.append({'species':row['species'],'category':row['category'],'target_count':5,'ready_count':nready,'shortfall_count':row['shortfall_to_five'],'missing_knowledge_type':sg['status'],
 'best_remaining_candidates':g.get('best_remaining_candidates',[]),'recommended_source_type':g.get('recommended_source_type','official/research aquaculture source with page-level evidence'),
 'required_verification':g.get('required_verification',[]),'source_search_performed':False,'structural_infeasibility':'not_assessed_before_targeted_source_search'})
hr= j(S/'high_risk_source_audit.json'); hritems=[{'candidate_id':x['candidate_id'],'species':x['species'],'category':x['category'],'document_id':x['document_id'],'page':x['page'],'source_title':x['source_title'],
 'authority_claimed':x['official_authority'],'corpus_legal_status':x['legal_status'],'current_version_independently_confirmed':False,'exact_rule_independently_confirmed':False,
 'applicability':x['applicability'],'readiness_status':'needs_review','blockers':x['review_blockers'],'verified_ready':False,'medication_advice_generated':False} for x in hr['items']]
calcrows=[json.loads(x) for x in (S/'calculation_formula_registry_v1.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]; calcval=j(S/'calculation_validation.json'); dup=j(S/'evidence_fact_duplicates.json')
form=[x for x in calcrows if x.get('formula')]
calcdiag={'candidate_species_assignments':calcval['candidate_species_assignments_processed'],'unique_chunks':calcval['unique_candidate_chunks'],'literal_formula_cue_rows':calcval['literal_formula_candidates_extracted'],
 'formula_candidates':[{'formula_id':x.get('formula_id'),'species':x.get('species'),'formula':x.get('formula'),'source_document':x.get('source_document'),'source_page':x.get('source_page'),'verification_status':x.get('verification_status'),
 'missing':['variables/definitions','units','valid range/input constraints','assumptions','rounding','tolerance','source verification']} for x in form[:5]],
 'formula_duplicate_groups':dup.get('formula_duplicate_groups',[]),'verified_formula_count':0,'deterministic_gold_answers_created':0,'candidate_llm_or_judge_used_for_gold':False}
normal=all(r['shortfall_to_five']==0 for r in matrix if r['category'] in ('Fact','Water Quality','Disease','Climate','Climate / Cold'))
strict=all(r['shortfall_to_five']==0 for r in matrix); high=False; calc_ready=False; cr=bool(ready2['final_corpus_ready']); er=bool(ready2['e4_final_ready'])
phase=bool(normal and high and calc_ready and strict and cr and er)
wl('verification_pilot_candidates.jsonl',candidates); wl('verification_pilot_decisions.jsonl',decisions); wl('promoted_evidence_units.jsonl',promoted)
wj('evidence_fact_duplicates.json',{'step2_audit':dup,'pilot_promoted_units':len(promoted),'pilot_duplicate_groups':[],'pilot_duplicate_groups_count':0,'pilot_duplicate_units_excluded':0,'formula_duplicate_groups':dup.get('formula_duplicate_groups',[]),'no_fact_padding':True})
wj('normal_risk_promotion.json',{'reviewed':len(decisions),'silver_ready':len(promoted),'needs_review':sum(x['readiness_status']=='needs_review' for x in decisions),'rejected_after_verification':0,'human_reviewed':False,'human_gold_claimed':False})
wl('high_risk_units.jsonl',hritems); wj('high_risk_source_audit.json',{'candidate_assignments':hr['candidate_assignment_count'],'unique_chunks':hr['unique_candidate_chunk_count'],'items':hritems,'verified_ready_count':0,'official_only':True,'source_additions':0,
 'blockers':['Current law version/effective date and exact provision not independently verified.','All candidate applicability remains unknown; species scope unresolved.','No medication dose/withdrawal advice generated.']})
wl('calculation_formula_registry_v1.jsonl',calcrows); wj('calculation_validation.json',calcdiag)
wj('pilot_evidence_matrix.json',{'species_count':6,'category_count':6,'cell_count':36,'target_distinct_units_per_cell':5,'candidate_assignments_are_not_units':True,'cells':matrix,
 'summary':{'pilot_reviewed':len(decisions),'new_silver_ready':len(promoted),'new_verified_ready':0,'ready_5_plus':sum(r['shortfall_to_five']==0 for r in matrix),'partial_1_to_4':sum(1<=5-r['shortfall_to_five']<=4 for r in matrix),'no_ready_units':sum(5-r['shortfall_to_five']==0 for r in matrix),'no_screened_candidate':sum(r['original_screened_count']==0 for r in matrix),'structurally_infeasible':0,'source_search_performed':False}})
wj('remaining_gap_analysis.json',{'source_search_performed':False,'source_additions':0,'target_count':5,'cells':remain,'priority_recommendations':['Target official/research sources for zero-candidate cells.','Acquire original source files for pending tilapia, mullet climate, milkfish and eel candidates.','Find distinct facts for partial cells; avoid paraphrase/formula padding.','Inspect eel Fact bibliography candidates for actual answerable propositions.']})
wj('readiness_after_step2b.json',{'pilot_candidates_reviewed':len(decisions),'new_silver_ready_units':len(promoted),'new_verified_ready_units':0,'normal_evidence_ready':normal,'high_risk_ready':high,'calculation_ready':calc_ready,'strict_matrix_ready':strict,'final_corpus_ready':cr,'e4_final_ready':er,'phase20_2_benchmark_construction_ready':phase,'source_additions_this_run':0,'winner':None,
 'reason':'Seven source-backed Silver units passed; target of five distinct units per cell remains unmet; no high-risk or calculation unit passed its stricter gate.'})
print(json.dumps({'reviewed':len(decisions),'promoted':len(promoted),'cells':len(matrix),'zero_candidate':sum(r['original_screened_count']==0 for r in matrix),'phase20_2_ready':phase}))
