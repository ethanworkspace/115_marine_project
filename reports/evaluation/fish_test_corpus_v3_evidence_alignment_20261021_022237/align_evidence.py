"""Source-first evidence ledger; semantic review maps are explicit and inspectable.
Candidate discovery is lexical, but it never grants FULL/PARTIAL support. Only
the separately reviewed, source-located clauses in curated_requirements do so.
"""
from pathlib import Path
import json, sqlite3, hashlib, re, collections, html, datetime
from decimal import Decimal
from curated_requirements import REQUIREMENTS,FULL,PARTIAL,ANSWERS,CALCS,SCOPE_UNVERIFIED,MISSING_CONDITIONS,POLICY_ABSTENTION
from focused_context_review import reviewed_label
W=Path(__file__).resolve().parent; ROOT=W.parents[2]
def read(p):return [json.loads(s) for s in Path(p).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def dump(n,x):(W/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jl(n,x):(W/n).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in x),encoding='utf-8')
def h(t):return hashlib.sha256(t.encode()).hexdigest()

# Semantic topic inventory: only for transparent candidate discovery / flagging.
# Absence of a term is never a negative relevance label.
CONCEPTS={
 'temperature':['水溫','溫度','低溫','寒流','℃','°C'],
 'ph':['pH','酸性','鹼性'], 'salinity':['鹽度','鹹度','psu','ppt','千分之'],
 'oxygen':['溶氧','缺氧','水車','停電','增氧'], 'stocking':['密度','放養','每公頃','尾/','尾／','公斤以下'],
 'reproduction':['繁殖','產卵','生殖','受精卵','孵化','成熟','種魚'],
 'cold':['寒流','防寒','越冬','防風','加溫','浮魚'],
 'feeding':['飼料','攝餌','投餌','食慾','吃餌','攝食','停口'],
 'grading':['分養','篩選','體型','分級'], 'disease':['病毒','寄生蟲','病原','確診','送驗','疾病','病害','診斷','感染'],
 'biosecurity':['消毒','隔離','交互污染','生物安全','無帶病毒','無染病'],
 'law':['法規','用藥','停藥','抗生素','劑量','許可','登錄','法令'],
 'organic':['有機物','底泥','殘餌','藻','水色','硫化氫'],
 'design':['坡度','水深','網片','浮框','網目','水管','進排水','棚'],
 'statistics':['統計','年度','2020','縣市','放養量']}
def topics(t):return {k for k,words in CONCEPTS.items() if any(x.lower() in t.lower() for x in words)}
def main():
 con=sqlite3.connect(W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3');con.row_factory=sqlite3.Row
 chunks={r['chunk_id']:dict(r) for r in con.execute('select * from chunks')}
 for x in chunks.values():x.pop('embedding',None)
 recs={r['source_record_id']:{**dict(r),'raw':json.loads(r['original_record_json'])} for r in con.execute('select * from source_records')}
 sources={r['source_id']:dict(r) for r in con.execute('select * from sources')};con.close()
 qs=read(W/'questions_original_180.jsonl');retr=read(W/'retrieval_results_alignment_final_180.jsonl');retmap={x['question_id']:x for x in retr}
 assert len(qs)==len(retr)==180 and len(retmap)==180
 # Every original dataset snapshot is re-hashed; source identity is independent of answer correctness.
 integrity=[]
 for s in sources.values():
  p=Path(s['source_file']); actual=hashlib.sha256(p.read_bytes()).hexdigest()
  integrity.append({'source_id':s['source_id'],'source_file':str(p),'expected_sha256':s['source_sha256'],'actual_sha256':actual,'match':actual==s['source_sha256'],'owner_admission':s['owner_admission_status'],'license_scope':s['license_scope_status'],'source_version':s['version_status']})
 assert all(x['match'] for x in integrity);dump('source_integrity_recheck.json',integrity)
 finite={x['chunk_id']:x for x in read(W/'finite_fact_provenance.jsonl')}
 def support_span(cid):
  ch=chunks[cid];r=recs[ch['source_record_id']];raw=r['raw'];q=ch['source_quote']
  if 'exact_original_quote' in raw:
   return {'chunk_id':cid,'source_id':ch['source_id'],'source_record_id':ch['source_record_id'],'source_version':ch['source_version'],'source_sha256':ch['source_sha256'],'exact_evidence_span':raw['exact_original_quote'],'evidence_locator':ch['locator'],'original_quote_start':raw['quote_start'],'original_quote_end':raw['quote_end'],'original_quote_verified':True,'raw_text_indexed':False,'representation':ch['text']}
  text=raw.get('description','');pos=text.find(q)
  result={'chunk_id':cid,'source_id':ch['source_id'],'source_record_id':ch['source_record_id'],'source_version':ch['source_version'],'source_sha256':ch['source_sha256'],'exact_evidence_span':q,'evidence_locator':ch['locator'],'original_quote_start':pos if pos>=0 else None,'original_quote_end':pos+len(q) if pos>=0 else None,'original_quote_verified':pos>=0,'raw_field':'/description','transform_rule':ch['transform_rule']}
  if pos<0:
   # Keep normalized source location explicitly distinct from raw byte/character position.
   result['normalized_quote_verified']=ch['text'].find(q)>=0
  return result
 profiles=[];availability=[];hits=[];references=[];rubrics=[];discovery=[]
 for q in qs:
  qid=q['question_id'];fish=qid.split('-')[1];num=int(qid[-2:]);requirement=REQUIREMENTS[fish][num-1]
  qt=topics(q['question_text']+' '+requirement)
  elements=[x for x in requirement.split('；') if x]
  profile={'question_id':qid,'original_question':q['question_text'],'species':q['species_chinese'],'scientific_scope':{'eel':'Anguilla japonica','seabass':'Lates calcarifer','grouper':'Epinephelus spp.'}.get(fish,q.get('species_label_in_test_data')),'category':q.get('inferred_category'),'required_answer_elements':elements,'numeric_values_and_units_in_question':re.findall(r'\d+(?:[,.]\d+)*(?:\s*(?:°C|℃|ppt|psu|ppm|mg/L|cm|kg|m³|公頃|尾|日|天|月|%|度))?',q['question_text']),'time_place_conditions':requirement,'formula_required':qid in CALCS or q.get('inferred_category')=='Calculation','high_risk_law_or_medication':bool(qt&{'law'}),'version_requirement':'Exact historical source requested by question; current legal status must be independently established for current prescribing/legal claims','method':'Codex source-blind question/options semantic requirement review; no M1-M4 generated answers read','human_gold':False}
  profiles.append(profile)
  # Search the entire admitted collection (including raw records omitted by old exact-fish screening).
  # Candidate finding is NOT evidence verification. Every hit is retained for reproducibility.
  cand=[]
  for rid,r in recs.items():
   raw=r['raw'];t=str(raw.get('title',''))+'\n'+str(raw.get('description',''))
   if r['source_id']=='MOA-TFRI-OPEN-114846' and topics(t)&qt:
    if q['species_chinese'] in t or rid in {'114846-ROW-0742','114846-ROW-0434','114846-ROW-0348','114846-ROW-0472'}:
     cand.append(rid)
  exact=FULL.get(qid,[]);part=PARTIAL.get(qid)
  allspans=[support_span(cid) for cid in exact or (part or {}).get('chunks',[])]
  if exact:
   assert all(chunks[cid]['retrieval_eligible'] for cid in exact)
   assert all(s['original_quote_verified'] for s in allspans),(qid,allspans)
   state='FULL_SUPPORT';reason='All frozen question-specific answer elements are supported by the explicitly reviewed original clauses, with the limits stated in the reference.'
  elif part:
   state='PARTIAL_SUPPORT';reason=part['reason']
  elif qid in SCOPE_UNVERIFIED:
   state='SOURCE_SCOPE_UNVERIFIED';reason='The likely cited Q&A concerns giant mottled eel (鱸鰻), whereas the original workbook targets Anguilla japonica. The biological/management value is not generalized; physical floating-feed property and explicitly Japanese-eel grading are separately qualified.'
   allspans=[support_span('TFRI-114846-0348-C14')]
  elif qid in MISSING_CONDITIONS:
   state='QUESTION_CONDITIONS_MISSING';reason='Symptoms or a single environmental measurement do not fix a diagnosis, an authorized product/dose or an inevitable death time. This is a scoped system-safety abstention test, not a universal scientific no-answer claim.'
  else:
   state='SOURCE_NOT_FOUND_IN_CORPUS';reason='No fully verified answer for the specified species, source version, values and conditions was located in this admitted snapshot. Entire-corpus candidate discovery and explicit source-clause review were performed; this is a bounded negative search result, not proof of global absence.'
  returned={x['chunk_id'] for x in retmap[qid]['top5']};found=set(exact)&returned
  # A source-record sibling only counts if it actually contains the same quoted answer clause.
  equivalent={}
  for cid in exact:
   quote=chunks[cid]['source_quote']; equivalents=[h['chunk_id'] for h in retmap[qid]['top5'] if quote in h['source_quote'] and h['source_id']==chunks[cid]['source_id']]
   if cid=='TFRI-114846-0348-C09':
    # Source-read semantic equivalence: all three explicitly name Japanese eel,
    # first grading after2months, then1–1.5months. A missing 約 is not a miss.
    equivalents += [x['chunk_id'] for x in retmap[qid]['top5'] if x['chunk_id'] in {'TFRI-114846-0436-C05','TFRI-114846-0472-C06'}]
   if cid=='TFRI-114846-0348-C20':
    equivalents += [x['chunk_id'] for x in retmap[qid]['top5'] if x['chunk_id'] in {'TFRI-114846-0436-C08','TFRI-114846-0472-C10'}]
   equivalent[cid]=equivalents
  retrieved_full=bool(exact) and all(cid in returned or equivalent[cid] for cid in exact)
  if exact:classification='SOURCE_SUPPORTED_RETRIEVED' if retrieved_full else 'SOURCE_SUPPORTED_NOT_RETRIEVED'
  elif part:classification='SOURCE_PARTIAL_ONLY'
  else:classification=state
  origin_keys={('PDF:'+s['source_sha256']+':'+str(recs[s['source_record_id']]['raw'].get('physical_page'))) if 'exact_original_quote' in recs[s['source_record_id']]['raw'] else 'JSON:'+s['source_record_id'] for s in allspans}
  base={'question_id':qid,'species':q['species_chinese'],'category':q.get('inferred_category'),'original_question':q['question_text'],'requirement_profile':profile,'corpus_version':'3.0.1-evidence-alignment','corpus_evidence_availability':state,'gap_classification':classification,'source_evidence':allspans,'verified_support_chunk_ids':exact,'partially_supported_chunk_ids':(part or {}).get('chunks',[]),'independent_support_record_count':len(origin_keys),'original_record_group_keys':sorted(origin_keys),'independent_source_file_count':len({s['source_sha256'] for s in allspans}),'source_search_record_count':len(recs),'whole_tfri_original_records_searched':956,'candidate_record_ids_from_entire_corpus':cand,'candidate_search_does_not_assign_relevance':True,'review_reason':reason,'verification_level':'AUTO_SOURCE_CHECKED; CODEX_SEMANTIC_CLAUSE_REVIEW; NOT_HUMAN_GOLD','remaining_human_validation':True}
  availability.append(base)
  hits.append({'question_id':qid,'corpus_evidence_availability':state,'retrieval_evidence_hit':retrieved_full if exact else None,'qualified_source_evidence_chunk_ids':exact,'returned_top5_ids':list(returned),'supporting_chunks_retrieved':sorted(found),'equivalent_quote_hits':equivalent,'gap_classification':classification,'top5_count':len(returned),'retrieval_failure_only_if_full_corpus_support_exists':True})
  discovery.append({'question_id':qid,'topics_for_candidate_discovery':sorted(qt),'searched_source_record_count':len(recs),'tfrin_candidate_record_ids':cand,'candidate_semantics_not_truth':True})
  if exact:
   calc=CALCS.get(qid); expected=ANSWERS[qid]
   if calc:
    a,b=Decimal(calc['a']),Decimal(calc['b']);value={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert value==Decimal(calc['expected'])
   r={'question_id':qid,'original_question':q['question_text'],'species':q['species_chinese'],'category':q.get('inferred_category'),'required_answer_elements':elements,'reference_answer':expected,'source_record_ids':sorted({s['source_record_id'] for s in allspans}),'evidence_spans':allspans,'source_versions':sorted({s['source_version'] for s in allspans}),'required_conditions':requirement,'expected_calculation':calc,'arithmetic_formula':(f"{calc['a']} {calc['operation']} {calc['b']}" if calc else None),'units':calc['unit'] if calc else None,'tolerance':calc['tolerance'] if calc else None,'evidence_verification_level':'ANSWERABLE_AUTO_SOURCE_CHECKED','human_review_status':'NOT_HUMAN_GOLD; PENDING_INDEPENDENT_REVIEW','eligibility_independent_of_top5':True,'logical_rubric':{'required_conclusion':expected,'required_conditions':elements,'prohibited_errors':['Unsupported cross-species transfer','Current drug permission/dose/withdrawal inferred from historical permit or generic law','A historical observed/reference range represented as guaranteed safety','An unsupported exact death time'],'allowed_alternatives':'Semantically equivalent conclusion with same conditions and source-supported values; no text-similarity scoring','scoring_rule':'correct only if every required conclusion/condition is observable; incorrect for a material contradicted conclusion; not_evaluable if not reliably parseable or reference applicability remains unresolved','source_evidence_chunk_ids':exact} if not calc else None,'knowledge_group_id':('KG-'+h('|'.join(sorted(exact)))[:12]),'formula_group_id':calc['protocol'] if calc else None,'frozen_before_new_generator_answers':True}
   r['rubric_sha256']=h(json.dumps(r,ensure_ascii=False,sort_keys=True));references.append(r);rubrics.append(r)
  elif qid in POLICY_ABSTENTION:
   references.append({'question_id':qid,'original_question':q['question_text'],'species':q['species_chinese'],'category':q.get('inferred_category'),'reference_answer':None,'eligibility':'EXPECTED_ABSTENTION_VERIFIED','basis':'Frozen source-restricted research-system safety policy; not an independently verified clinical diagnosis or universal no-answer gold','expected_abstention':True,'missing_conditions':['No confirmed pathogen/diagnosis','No identified authorized product and applicable labelled dose','No complete patient/environment context'],'professional_accuracy_eligible':False,'human_review_status':'NOT_HUMAN_GOLD','evidence_verification_level':'SYSTEM_POLICY_VERIFIED_ONLY'})
  else:references.append({'question_id':qid,'original_question':q['question_text'],'species':q['species_chinese'],'category':q.get('inferred_category'),'reference_answer':None,'eligibility':'PARTIALLY_SUPPORTED' if part else 'NOT_EVALUABLE','reason':reason,'evidence_spans':allspans,'human_review_status':'NOT_HUMAN_GOLD','professional_accuracy_eligible':False})
 # Support labels: a manually reviewed clause map grants positive labels.
 # All other candidate screens retain explicit diagnostic vs verified boundaries.
 def label(q,ch,rank,stage):
  qid=q['question_id'];req=REQUIREMENTS[qid.split('-')[1]][int(qid[-2:])-1];cid=ch['chunk_id'];target=q['species_chinese'];scope=chunks[cid]['species_scope'].split('|');t=ch['source_quote'];raw=recs[ch['source_record_id']]['raw'];qt=topics(q['question_text']+' '+req);ct=topics(t)
  supported=[];missing=[req];sp=support_span(cid);relevant=None;verified=False
  if cid in FULL.get(qid,[]):
   status='FULL_SUPPORT' if len(FULL[qid])==1 else 'PARTIAL_SUPPORT';supported=[req] if status=='FULL_SUPPORT' else ['Explicit source clause covers part of the frozen multi-clause reference'];missing=[] if status=='FULL_SUPPORT' else ['Other required source clause(s): '+', '.join(x for x in FULL[qid] if x!=cid)];relevant=1;verified=sp['original_quote_verified'];reason='Question-specific semantic clause-to-requirement review; exact source locator verified.'
  elif cid in PARTIAL.get(qid,{}).get('chunks',[]):
   status='CONFLICT' if qid.startswith('FT-tilapia-') and int(qid[-2:]) in (1,2,4,19,20,22) else 'PARTIAL_SUPPORT';relevant=None if status=='CONFLICT' else 1;reason=PARTIAL[qid]['reason'];verified=sp['original_quote_verified'];supported=['Only the elements explicitly described by the partial-support reason']
  elif 'OTHER_SPECIES' in scope or 'GIANT_MOTTLED_EEL_ONLY' in scope:
   status='SPECIES_MISMATCH';relevant=0;verified=True;reason='Reviewed paragraph subject is an explicitly different taxon; record-level target-fish mentions do not establish applicability.'
  elif ch['source_id']=='MOA-ANIMAL-DRUG-OPEN-7274':
   status='TOPICAL_ONLY';relevant=0;verified=True;reason='The question does not request this named permit field. This permit snapshot does not establish the requested diagnosis, current permission, prescribed dose or withdrawal protocol; expiration/version are separate.'
  elif cid.startswith(('DGBAS-','MOA-EEL-STOCKING')):
   status='IRRELEVANT';relevant=0;verified=True;reason='Statistical snapshot does not supply this original husbandry/clinical answer. DGBAS limited 2020 scope and no-year eel context-only restriction retained.'
  elif target not in scope and not any(s.startswith('GENERAL_') for s in scope):
   status='UNVERIFIED';reason='Paragraph-level target applicability remains unverified; no negative label inferred solely from absence of a species string.'
  elif cid.startswith('FA385-'):
   if qt&{'cold'}:
    status='TOPICAL_ONLY';relevant=0;verified=True;reason='This finite cold-management fact supplies a different operation/value than the question requires: '+req
   else:status='IRRELEVANT';relevant=0;verified=True;reason='Finite cold-management fact does not supply the requested non-cold information: '+req
  elif cid.startswith('M17-SEABASS-'):
   status='TOPICAL_ONLY';relevant=0;verified=True;reason='The finite temperature/salinity/fry-stock fact is not the particular answer element requested: '+req
  elif qt and ct and not qt&ct:
   # Topic inventories are a screen, never enough to accept a negative truth.
   status='UNVERIFIED';reason='Candidate topic inventory differs; independent content relevance has not been fixed. No low-overlap rejection is used.'
  elif qt&ct:
   status='TOPICAL_ONLY';reason='The paragraph addresses related concepts, but no exact question-specific answer element has been independently matched. This remains an exploratory diagnostic, not a reliable binary relevance label.'
  else:status='UNVERIFIED';reason='Content support not established by a source-located semantic clause review.'
  # Preserve sibling corroboration only with an exact already-reviewed answer sentence.
  if status not in ('FULL_SUPPORT','PARTIAL_SUPPORT'):
   for refcid in FULL.get(qid,[]):
    rq=chunks[refcid]['source_quote']
    if ch['source_id']==chunks[refcid]['source_id'] and rq in t and target in scope:
     status='PARTIAL_SUPPORT';relevant=1;verified=sp['original_quote_verified'];reason='Exact already-reviewed supporting clause appears in this sibling span; record identity is not counted as an independent source.';supported=[req];break
  manual=reviewed_label(qid,rank,cid) if stage=='3.0.1-evidence-alignment' else None
  if manual:
   relevant,status,reason=manual;verified=True
   if relevant==1:supported=[reason]
  return {'question_id':qid,'chunk_id':cid,'rank':rank,'retrieval_stage_version':stage,'source_id':ch['source_id'],'source_record_id':ch['source_record_id'],'source_version':ch['source_version'],'source_sha256':ch['source_sha256'],'corpus_evidence_availability':next(a['corpus_evidence_availability'] for a in availability if a['question_id']==qid),'support_label':status,'relevance_label':relevant,'reliable_binary_label_for_exploratory_p5':bool(verified and relevant in (0,1)),'matched_answer_elements':supported,'missing_answer_elements':missing,'required_values_units_conditions':req,'exact_evidence_span':t,'evidence_locator':ch['exact_locator'],'original_quote_verification':sp,'species_scope':scope,'reason':reason,'focused_content_review':bool(manual),'verification_level':'AI_ASSISTED_SOURCE_ALIGNMENT; NOT_HUMAN_GOLD','human_gold':False,'annotation_confidence':'source-located rule/semantic review' if verified else 'NOT_INDEPENDENTLY_VALIDATED','needs_review':True}
 newlabels=[]
 for q in qs:
  for x in retmap[q['question_id']]['top5']:newlabels.append(label(q,x,x['rank'],'3.0.1-evidence-alignment'))
 old=read(ROOT/'reports/evaluation/fish_test_corpus_v3_integration_20261021_003519/retrieval_results_v3_180.jsonl')
 oldlabels=[]
 for r in old:
  q=next(q for q in qs if q['question_id']==r['question_id'])
  for x in r['top5']:oldlabels.append(label(q,x,x['rank'],'3.0.0-original-792-audit'))
 p5=[]
 for q in qs:
  ls=[x for x in newlabels if x['question_id']==q['question_id']];valid=len(ls)==5 and all(x['reliable_binary_label_for_exploratory_p5'] for x in ls)
  relevant=sum(x['relevance_label']==1 and x['reliable_binary_label_for_exploratory_p5'] for x in ls);uncertain=5-sum(x['relevance_label'] in (0,1) and x['reliable_binary_label_for_exploratory_p5'] for x in ls)
  p5.append({'question_id':q['question_id'],'species':q['species_chinese'],'category':q.get('inferred_category'),'top5_count':len(ls),'reliably_binary_labeled_count':5-uncertain,'p_at_5':relevant/5 if valid else None,'lower_bound':relevant/5,'upper_bound':(relevant+uncertain)/5,'status':'AI_ASSISTED_EXPLORATORY_P5_NOT_HUMAN_GOLD' if valid else 'NOT_EVALUABLE','reason':None if valid else ('FEWER_THAN_5_CONTEXTS' if len(ls)<5 else 'RELIABLE_BINARY_RELEVANCE_LABELS_INCOMPLETE'),'shared_across_four_generators':True})
 prior=read(ROOT/'reports/evaluation/fish_test_phase_aa_20261019_220906/reference_answers_frozen.jsonl')
 revalidation=[]
 for r in prior:
  if r.get('verification_status')!='SOURCE_VERIFIED_AUTOMATED':continue
  qid=r['question_id'];nr=next(x for x in references if x['question_id']==qid)
  actual=hashlib.sha256(Path(r['source_file']).read_bytes()).hexdigest()
  revalidation.append({'question_id':qid,'previous_source_id':r['source_id'],'previous_source_file':r['source_file'],'previous_source_sha256_expected':r['source_sha256_expected'],'previous_source_sha256_actual':actual,'file_identity_verified':actual==r['source_sha256_expected'],'previous_identity_not_answer_proof':True,'current_evidence_verification':nr.get('evidence_verification_level',nr.get('eligibility')),'current_corpus_evidence':nr.get('evidence_spans',[]),'current_source_record_ids':nr.get('source_record_ids',[]),'old_fulltext_imported':False,'decision':'Reverified through explicitly located current source clauses' if qid in FULL else 'Historical candidate retained; exact requested range/version not established in the current admitted corpus','limitation':None if qid in FULL else 'Grouper manual 25–30°C differs from original question source 25–29°C; cannot silently substitute ranges.'})
 assert len(revalidation)==13
 # Every quantity is derived from its matching ledger, never hardcoded expectations.
 summary={'total_questions':len(qs),'original_top5_context_count':sum(len(r['top5']) for r in old),'updated_top5_context_count':len(newlabels),'questions_with_context':sum(bool(r['top5']) for r in retr),'questions_with_full_top5':sum(len(r['top5'])==5 for r in retr),'corpus_evidence_availability_counts':dict(collections.Counter(a['corpus_evidence_availability'] for a in availability)),'gap_classification_counts':dict(collections.Counter(a['gap_classification'] for a in availability)),'frozen_source_checked_reference_count':sum('evidence_verification_level' in r and r['evidence_verification_level']=='ANSWERABLE_AUTO_SOURCE_CHECKED' for r in references),'logical_rubric_eligible_question_count':sum(bool(r.get('logical_rubric')) for r in references),'source_bound_applied_arithmetic_question_count':len(CALCS),'fcr_sgr_bfcr_validated_question_count':0,'human_gold':0,'source_counts_before':dict(collections.Counter(c['source_id'] for r in old for c in r['top5'])),'source_counts_after':dict(collections.Counter(c['source_id'] for r in retr for c in r['top5'])),'unique_record_count_before':len({c['source_record_id'] for r in old for c in r['top5']}),'unique_record_count_after':len({c['source_record_id'] for r in retr for c in r['top5']}),'relevance_label_counts':dict(collections.Counter(x['support_label'] for x in newlabels)),'ai_semantics_not_classification_ground_truth':True,'negative_search_limit':'Source-not-found is limited to this snapshot and the documented candidate/clauses review; new independent professional review may discover additional support.'}
 species={}
 for s in sorted({q['species_chinese'] for q in qs}):
  aa=[a for a in availability if a['species']==s];pp=[r for r in p5 if r['species']==s and r['p_at_5'] is not None];species[s]={'questions':len(aa),'full_source_support':sum(a['corpus_evidence_availability']=='FULL_SUPPORT' for a in aa),'partial_source_support':sum(a['corpus_evidence_availability']=='PARTIAL_SUPPORT' for a in aa),'full_support_retrieved':sum(a['gap_classification']=='SOURCE_SUPPORTED_RETRIEVED' for a in aa),'full_support_not_retrieved':sum(a['gap_classification']=='SOURCE_SUPPORTED_NOT_RETRIEVED' for a in aa),'logical_eligible':sum(r.get('species')==s and bool(r.get('logical_rubric')) for r in references),'arithmetic_eligible':sum(r.get('species')==s and bool(r.get('expected_calculation')) for r in references),'p5_evaluable':len(pp),'p5_mean':sum(r['p_at_5'] for r in pp)/len(pp) if pp else None}
 category={cat:dict(collections.Counter(a['corpus_evidence_availability'] for a in availability if a['category']==cat)) for cat in sorted({a['category'] for a in availability})}
 summary['species']=species;summary['categories']=category
 status={'formula':'P@5 = relevant / 5','full_top5_questions':summary['questions_with_full_top5'],'questions_with_reliable_binary_labels':sum(r['p_at_5'] is not None for r in p5),'mean_exploratory_p5':(sum(r['p_at_5'] for r in p5 if r['p_at_5'] is not None)/sum(r['p_at_5'] is not None for r in p5)) if any(r['p_at_5'] is not None for r in p5) else None,'status':'AI_ASSISTED_EXPLORATORY_NOT_INDEPENDENT_HUMAN_GOLD','all_180_p5_not_claimed':True,'formal_professional_p5':None,'questions':p5}
 freeze={'version':'evidence-alignment-rubric-1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'corpus_manifest':json.loads((W/'corpus_successor_manifest.json').read_text()),'method':'Explicit source-first clause alignment before new generator answers; not original workbook candidate-answer similarity','question_profiles_sha256':h(json.dumps(profiles,ensure_ascii=False,sort_keys=True)),'references':rubrics,'logical_n':summary['logical_rubric_eligible_question_count'],'source_bound_applied_arithmetic_n':len(CALCS),'arithmetic_scope_limitation':'Dimensional scaling, differences, intervals only; no newly verified FCR/SGR/bFCR protocol; pure question-stem diagnostics are excluded.','p5_binary_rule':'Applicable, source-located substantive full or partial required-answer-element support. Topic overlap or reranker score is insufficient.','human_gold':0,'frozen_before_new_generator':True}
 freeze['rubric_registry_sha256']=h(json.dumps(freeze,ensure_ascii=False,sort_keys=True))
 existing_freeze=W/'evaluation_rubrics_v3_frozen.json'
 if existing_freeze.exists():
  previous=json.loads(existing_freeze.read_text(encoding='utf-8'))
  assert previous['references']==rubrics,'Do not revise an answer rubric after new generation.'
  freeze=previous
 jl('question_requirement_profiles_reviewed_180.jsonl',profiles);jl('whole_corpus_candidate_search_180.jsonl',discovery);jl('corpus_evidence_availability_180.jsonl',availability);jl('retrieval_evidence_hits_180.jsonl',hits);jl('retrieved_chunk_support_labels.jsonl',newlabels);jl('original_792_chunk_support_audit.jsonl',oldlabels);jl('previous_13_answers_revalidation.jsonl',revalidation);jl('verified_reference_answers_v3.jsonl',references);dump('evaluation_rubrics_v3_frozen.json',freeze);dump('context_precision_label_status.json',status);dump('evidence_alignment_summary.json',summary)
 print(json.dumps({k:v for k,v in summary.items() if k not in ('species','categories')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
