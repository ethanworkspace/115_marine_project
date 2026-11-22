"""Frozen-context, serial four-model re-evaluation of the active research RAG."""
from __future__ import annotations
import argparse,collections,copy,hashlib,importlib,json,os,pathlib,re,shutil,sqlite3,subprocess,sys,time
from datetime import datetime,timezone,timedelta
from decimal import Decimal

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import requests
POINTER=ROOT/'research_staging/unified_rag_v6_evaluation_pointer.json'
OLD=ROOT/'reports/evaluation/fish_test_final_fixed_denominator_run_20261023_010143'
APP=ROOT/'research_staging/app_sessions/launch_20261118_154253'
PY=ROOT/'reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237/test_env/Scripts/python.exe'
MODEL_SPECS={
 'M1':{'tag':'deepseek-r1:7b','digest':'755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f','architecture':'qwen2'},
 'M2':{'tag':'qwen2.5-coder:7b','digest':'dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364','architecture':'qwen2'},
 'M3':{'tag':'hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M','digest':'aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42','architecture':'llama'},
 'M4':{'tag':'gemma2:9b','digest':'ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b','architecture':'gemma2'},
}
JUDGE={'tag':'mistral-nemo:12b-instruct-2407-q4_K_M','digest':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55'}
BGE={'tag':'bge-m3:latest','digest':'7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'}

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat()
def read(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def jl(p):return [json.loads(line) for line in pathlib.Path(p).read_text(encoding='utf-8').splitlines() if line.strip()] if pathlib.Path(p).exists() else []
def dump(p,obj):pathlib.Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def append(p,obj):
    with pathlib.Path(p).open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def sha(p):
    with pathlib.Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def emit(obj):print(json.dumps(obj,ensure_ascii=False),flush=True)
def work():return pathlib.Path(read(POINTER)['directory'])
def norm(text):return re.sub(r'\s+','',str(text))
def copy_file(a,b):shutil.copyfile(a,b);assert sha(a)==sha(b)

def baseline(w,name):
    source=ROOT/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json';rows=read(source)['files'];changed=[]
    for row in rows:
        p=ROOT/row['path']
        if not p.is_file() or sha(p)!=row['sha256']:changed.append(row['path'])
    actual=sha(ROOT/'rag_store.sqlite3');obj={'at':now(),'count':len(rows),'unchanged':len(rows)-len(changed),'changed':changed,'production_sqlite_sha256':actual,'production_matches':actual=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'}
    dump(w/('protected_'+name+'.json'),obj);assert not changed and obj['count']==636 and obj['production_matches'];return obj

def model_identity():
    tags={m['name']:m for m in requests.get('http://127.0.0.1:11434/api/tags',timeout=30).json()['models']};result={}
    for name,spec in {**MODEL_SPECS,'Judge':JUDGE,'BGE':BGE}.items():
        assert tags[spec['tag']]['digest']==spec['digest'],name+' digest mismatch'
        res=requests.post('http://127.0.0.1:11434/api/show',json={'model':spec['tag']},timeout=30);res.raise_for_status();show=res.json();arch=show.get('model_info',{}).get('general.architecture')
        if spec.get('architecture'):assert arch==spec['architecture'],name+' architecture mismatch'
        result[name]={**spec,'architecture_observed':arch,'details':show.get('details'),'model_info':show.get('model_info'),'parameters':show.get('parameters'),'template_sha256':digest(show.get('template'))}
    assert result['M3']['architecture_observed']=='llama';assert JUDGE['digest'] not in {v['digest'] for v in MODEL_SPECS.values()};return result

def init():
    active=read(ROOT/'research_staging/unified_rag_active.json');assert 'v6' in active['version'];assert sha(active['database'])==active['database_sha256']
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S');w=ROOT/'reports/evaluation'/('unified_rag_v6_evaluation_'+stamp);w.mkdir()
    for folder in ('prompts','streams','free_queries','logs','runtime_application','previews','outputs','scoring'): (w/folder).mkdir()
    for name in ('questions_original_180.jsonl','question_requirement_profiles_reviewed_180.jsonl','verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','fixed_denominator_scoring_policy.json','context_precision_reused_labels_60.jsonl'):
        copy_file(OLD/name,w/('previous_'+name if name in ('verified_reference_answers_v3.jsonl','evaluation_rubrics_v3_frozen.json','fixed_denominator_scoring_policy.json','context_precision_reused_labels_60.jsonl') else name))
    for name in ('answer_policy.py','free_question_engine.py','unified_question_engine.py'):
        copy_file(APP/name,w/'runtime_application'/name)
    for name in ('arithmetic_parser_v4.py','numeric_grounding_v3.py'):
        copy_file(OLD/name,w/'scoring'/name)
    dump(w/'corpus_active_snapshot.json',active);copy_file(pathlib.Path(active['workspace'])/'corpus_manifest.json',w/'corpus_manifest.json');copy_file(pathlib.Path(active['workspace'])/'source_registry.json',w/'source_registry.json')
    identity=model_identity();dump(w/'model_runtime_identity.json',identity)
    questions=jl(w/'questions_original_180.jsonl');assert len(questions)==len({x['question_id'] for x in questions})==180
    originals=[]
    for name in sorted({q['source_workbook'] for q in questions}):
        p=ROOT/'fish test'/name;h=sha(p);assert all(q['source_workbook_sha256']==h for q in questions if q['source_workbook']==name);originals.append({'path':str(p),'sha256':h})
    dump(w/'question_workbooks_integrity.json',{'originals':originals,'questions':len(questions),'species':dict(collections.Counter(q['species_chinese'] for q in questions)),'source_rows_retained':True})
    dump(w/'evaluation_config.json',{'run_id':w.name,'created_at':now(),'corpus':active,'source_application':str(APP),'model_order':list(MODEL_SPECS),'generator_options':'Exact options in copied unified application / fair_grounded_rag_final; captured per payload','target_pairs':len(questions)*len(MODEL_SPECS),'retry_policy':'At most 2 attempts on transport/API/stream failure only; no content-driven resampling','metrics':['faithfulness','judge_answer_relevance','bge_m3_cosine','structured_ifr','ttft_seconds','tps','peak_system_ram','peak_dedicated_vram','context_precision_at_5','logical_accuracy','arithmetic_accuracy'],'raw_and_system_separate':True,'fixed_denominators_revalidated_before_generation':True,'human_gold':0,'scope':'EXPLORATORY_V6_REGRESSION; reused exposed fish questions; no unseen holdout claim','no_weighted_total_or_winner':True})
    baseline(w,'before');dump(POINTER,{'directory':str(w)})
    emit({'directory':str(w),'models_verified':list(identity),'target':720})

def runtime(w):
    sys.path[:0]=[str(w/'runtime_application'),str(ROOT)]
    import answer_policy,free_question_engine,unified_question_engine
    for module in (answer_policy,free_question_engine,unified_question_engine):module.SESSION=w
    rt=unified_question_engine.UnifiedQuestionRag();active=read(w/'corpus_active_snapshot.json');assert rt.unified.sha==active['database_sha256'];return rt

def revalidate_references():
    w=work();active=read(w/'corpus_active_snapshot.json');con=sqlite3.connect(pathlib.Path(active['database']).as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    docs={r['sha256']:dict(r) for r in con.execute('SELECT document_id,sha256,source_version,rights_status,parse_status FROM documents')}
    chunks=collections.defaultdict(list)
    for r in con.execute('SELECT chunk_id,source_id,source_sha256,source_record_id,source_quote,text,source_version FROM chunks WHERE retrieval_eligible=1'):chunks[r['source_sha256']].append(dict(r))
    refs=jl(w/'previous_verified_reference_answers_v3.jsonl');out=[];audit=[]
    for ref in refs:
        item=copy.deepcopy(ref);full=ref.get('evidence_verification_level')=='ANSWERABLE_AUTO_SOURCE_CHECKED';checks=[]
        for span in ref.get('evidence_spans',[]):
            doc=docs.get(span.get('source_sha256'));quote=span.get('exact_evidence_span','');exact=False;match_kind=None
            if doc and quote:
                for page in con.execute('SELECT page,raw_text,cleaned_text FROM document_pages WHERE document_id=?',(doc['document_id'],)):
                    if quote in page['raw_text'] or quote in page['cleaned_text']:exact=True;match_kind='EXACT_NATIVE_PAGE_TEXT';break
                    if norm(quote) in norm(page['raw_text']) or norm(quote) in norm(page['cleaned_text']):exact=True;match_kind='WHITESPACE_ONLY_PAGE_NORMALIZATION';break
                if not exact:
                    records=con.execute('SELECT original_record_json FROM source_records WHERE source_record_id=?',(span.get('source_record_id'),)).fetchall()
                    for rec in records:
                        if norm(quote) in norm(json.dumps(json.loads(rec[0]),ensure_ascii=False)):exact=True;match_kind='EXACT_ORIGINAL_RECORD_PROVENANCE';break
            candidates=[]
            for c in chunks.get(span.get('source_sha256'),[]):
                original_match=quote and norm(quote) in norm(c['source_quote'])
                same_finite=span.get('representation') and norm(span['representation'])==norm(c['text'])
                if original_match or same_finite:candidates.append(c['chunk_id'])
            checks.append({'old_chunk_id':span.get('chunk_id'),'source_sha256':span.get('source_sha256'),'source_document_id':doc['document_id'] if doc else None,'original_quote_reproduced':exact,'verification_method':match_kind,'eligible_v6_chunk_ids':candidates,'source_location':span.get('evidence_locator'),'source_version_retained':span.get('source_version'),'availability_independent_of_top5':True})
        qualified=bool(full and checks and all(s['original_quote_reproduced'] and s['eligible_v6_chunk_ids'] for s in checks))
        calc=ref.get('expected_calculation')
        if qualified and calc:
            a,b=Decimal(calc['a']),Decimal(calc['b']);answer={'multiply':lambda:a*b,'subtract':lambda:a-b,'divide':lambda:a/b}[calc['operation']]();assert answer==Decimal(calc['expected']) and Decimal(calc['tolerance'])>=0
        item['previous_verification_status']=ref.get('evidence_verification_level',ref.get('eligibility'))
        item['v6_reference_checks']=checks;item['v6_professional_eligible']=qualified;item['v6_eligibility']='ANSWERABLE_AUTO_SOURCE_CHECKED' if qualified else 'PARTIALLY_SUPPORTED' if ref.get('eligibility')=='PARTIALLY_SUPPORTED' else 'NOT_EVALUABLE'
        item['v6_not_evaluable_reason']=None if qualified else 'PREVIOUSLY_UNQUALIFIED_REFERENCE_NOT_NEWLY_VERIFIED_THIS_RUN; additional corpus evidence is not ruled out; no assumed abstention truth'
        groups=[]
        for span in ref.get('evidence_spans',[]):
            match=re.search(r'PDF physical page\s+(\d+)',str(span.get('evidence_locator','')),re.I)
            groups.append('PDF:'+str(span.get('source_sha256'))+':'+match[1] if match else 'RECORD:'+str(span.get('source_record_id')))
        item['reference_source_group_ids']=sorted(set(groups));item['reference_source_file_sha256s']=sorted({s['source_sha256'] for s in ref.get('evidence_spans',[]) if s.get('source_sha256')})
        item['previous_rubric_sha256']=ref.get('rubric_sha256')
        item['rubric_sha256']=digest({k:item.get(k) for k in ('question_id','reference_answer','required_answer_elements','logical_rubric','expected_calculation','evidence_spans','v6_reference_checks','reference_source_group_ids')})
        item['human_gold']=False;item['frozen_before_new_generator_answers']=True
        out.append(item);audit.append({'question_id':ref['question_id'],'previous_full_reference':full,'v6_professional_eligible':qualified,'checks':checks})
    con.close()
    for name,rows in [('verified_reference_answers_v6.jsonl',out),('reference_revalidation_180.jsonl',audit)]:
        with (w/name).open('w',encoding='utf-8') as f:
            for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    good=[r for r in out if r['v6_professional_eligible']];logical=[r['question_id'] for r in good if r.get('logical_rubric')];arithmetic=[r['question_id'] for r in good if r.get('expected_calculation')]
    policy={'version':'v6-fixed-reference-denominator-20261121','source_question_ids':[r['question_id'] for r in good],'logical_question_ids':logical,'arithmetic_question_ids':arithmetic,'fixed_source_n':len(good),'fixed_logical_n':len(logical),'fixed_arithmetic_n':len(arithmetic),'all_question_n':180,'conditional_accuracy':'Correct / (correct + incorrect) only among interpretable answers with qualified frozen references; not_evaluable remains N/A','fixed_task_success':'Reference-correct complete observable content AND raw schema/citation/source checks / fixed eligible question set; refusal/incomplete/invalid count not successful','partial_status_not_automatically_complete_or_wrong':'Completeness judged against frozen required elements, not answer_status alone','system_guidance_not_professional_answer':True,'no_extraction_credit_to_model':True,'no_total_score':True,'human_gold':0}
    dump(w/'fixed_denominator_policy_v6.json',policy)
    dump(w/'evaluation_rubrics_v6_frozen.json',{'version':policy['version'],'references':good,'frozen_before_new_generator':True,'human_gold':0,'reference_sha256':sha(w/'verified_reference_answers_v6.jsonl')})
    emit({'stage':'reference_revalidation','full':len(good),'logical':len(logical),'arithmetic':len(arithmetic),'previous_full':sum(x['previous_full_reference'] for x in audit)})

def prepare():
    w=work();rt=runtime(w);questions=jl(w/'questions_original_180.jsonl');file=w/'shared_contexts_180.jsonl';done={x['question_id'] for x in jl(file)}
    if len(done)!=len(jl(file)):raise ValueError('Duplicate retrieval records')
    import torch
    from dataclasses import asdict
    from src.evaluation.reranker_runtime import CrossEncoderRuntime
    config=read(w/'evaluation_config.json');device=config.get('precompute_reranker_device','cuda')
    unload()
    if device=='cuda':
        assert torch.cuda.is_available(),'CUDA unavailable; do not silently mix preprocessing devices'
        torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    rt.unified.reranker=CrossEncoderRuntime(rt.unified.reranker_path,device=device,max_length=512,batch_size=config.get('precompute_reranker_batch_size',4))
    dump(w/'retrieval_runtime.json',{'reranker':asdict(rt.unified.reranker.load_info),'tf32_enabled':False,'query_embedding_model':BGE,'rrf_k':60,'same_pipeline_all_180':True})
    for q in questions:
        if q['question_id'] in done:continue
        r=rt.prepare_free_question(q['question_text'],q['species_chinese']);r['question_id']=q['question_id'];r['category']=q['inferred_category'];r['original_question_metadata']=q;r['run_id']=w.name;r['frozen_context_for_all_models']=True
        assert r['free_question'] and r['retrieval']['corpus_version']==read(w/'corpus_active_snapshot.json')['version'];append(file,r);done.add(r['question_id'])
        dump(w/'retrieval_checkpoint.json',{'completed':len(done),'target':len(questions),'at':now(),'last_question':q['question_id']});emit({'stage':'retrieval','completed':len(done),'question_id':q['question_id'],'context_count':len(r['top5'])})
    rows=jl(file);assert len(rows)==180;dump(w/'retrieval_summary.json',{'questions':len(rows),'any_context':sum(bool(r['top5']) for r in rows),'full_top5':sum(len(r['top5'])==5 for r in rows),'chunks_returned':sum(len(r['top5']) for r in rows),'species':dict(collections.Counter(r['species'] for r in rows)),'not_answer_support_truth':True})

def freeze():
    w=work();active=read(w/'corpus_active_snapshot.json');assert sha(active['database'])==active['database_sha256'];rows=jl(w/'shared_contexts_180.jsonl');assert len(rows)==len({r['question_id'] for r in rows})==180
    small=[w/n for n in ('questions_original_180.jsonl','question_requirement_profiles_reviewed_180.jsonl','verified_reference_answers_v6.jsonl','evaluation_rubrics_v6_frozen.json','fixed_denominator_policy_v6.json','shared_contexts_180.jsonl','model_runtime_identity.json','evaluation_config.json','metric_spec_v6.json','context_precision_labels_v6.jsonl','pre_run_e2e_validation.json','retrieval_runtime.json')]
    small+=list((w/'runtime_application').glob('*.py'))+list((w/'scoring').glob('*.py'))+list((w/'scoring').glob('*.json'))
    source_code=[]
    for folder in ('src/unified_rag_v4','src/unified_rag_v5','src/unified_rag_v6'):
        source_code.extend((ROOT/folder).glob('*.py'))
    source_code += [ROOT/'tools/evaluate_unified_rag_v6.py',ROOT/'tools/score_unified_rag_v6.py',ROOT/'tools/review_v6_context_precision.py']
    source_code += [OLD/n for n in ('fair_grounded_rag_final.py','runtime_base.py','bootstrap_repair.py','numeric_grounding_v3.py','arithmetic_parser_v4.py','retrieval_pipeline.py')]
    manifest={'run_id':w.name,'frozen_at':now(),'corpus':active,'files':[{'path':str(p),'sha256':sha(p)} for p in small+source_code],'context_count':len(rows),'context_policy':'One fixed v6 context per original question, shared by all four models; live deployed pipeline unchanged','model_specs':MODEL_SPECS,'judge':JUDGE,'embedding':BGE,'fixed_denominators':read(w/'fixed_denominator_policy_v6.json'),'human_gold':0,'scope':'EXPLORATORY_REGRESSION_NOT_UNSEEN_HOLDOUT'}
    dump(w/'frozen_evaluation_manifest.json',manifest);emit({'stage':'frozen','questions':len(rows),'files':len(manifest['files'])})

def preflight():
    import platform,psutil
    w=work();rt=runtime(w);rows=jl(w/'shared_contexts_180.jsonl');refs={x['question_id']:x for x in jl(w/'verified_reference_answers_v6.jsonl')}
    possible=[]
    for row in rows:
        ref=refs[row['question_id']];ids={c['chunk_id'] for c in row['top5']}
        if ref['v6_professional_eligible'] and ref.get('logical_rubric') and all(ids.intersection(check['eligible_v6_chunk_ids']) for check in ref['v6_reference_checks']):possible.append(row)
    if possible:positive=copy.deepcopy(possible[0]);positive_kind='ACTUAL_FROZEN_TOP5_WITH_REFERENCE_SUPPORT'
    else:
        ref=next(x for x in refs.values() if x['v6_professional_eligible'] and x.get('logical_rubric'));positive=copy.deepcopy(next(x for x in rows if x['question_id']==ref['question_id']));ids=list(dict.fromkeys(cid for check in ref['v6_reference_checks'] for cid in check['eligible_v6_chunk_ids']))[:5];positive['top5']=[{**rt.unified.map[cid],'rank':i+1} for i,cid in enumerate(ids)];positive['context_digest']=digest([{k:c.get(k) for k in ('chunk_id','source_sha256','source_version','text','source_quote')} for c in positive['top5']]);positive_kind='CONTROLLED_IN_CORPUS_SOURCE_FIXTURE_NOT_RETRIEVAL_HIT'
    positive['question_id']='PREFLIGHT-POSITIVE-'+positive['question_id'];empty=copy.deepcopy(positive);empty.update(question_id='PREFLIGHT-EMPTY',top5=[],context_digest=digest([]),source_group_ids=[])
    wrong=copy.deepcopy(positive);wrong.update(question_id='PREFLIGHT-WRONG-SPECIES',species='鰻魚' if positive['species']!='鰻魚' else '虱目魚')
    wrong['top5']=[c for c in positive['top5'] if c.get('species_scope') and wrong['species'] not in c['species_scope']]
    if not wrong['top5']:wrong['top5']=[next(c for c in rt.unified.rows if c.get('species_scope') and wrong['species'] not in c['species_scope'] and c.get('taxonomy_level')=='SPECIES_EXPLICIT')]
    wrong['context_digest']=digest([{k:c.get(k) for k in ('chunk_id','source_sha256','source_version','text','source_quote')} for c in wrong['top5']])
    drug=copy.deepcopy(empty);drug.update(question_id='PREFLIGHT-HIGH-RISK',question='鰻魚使用氯黴素的劑量與停藥天數是多少？',species='鰻魚',category='Medication / Law')
    cases=[('POSITIVE',m,positive) for m in MODEL_SPECS]+[('EMPTY','M2',empty),('WRONG_SPECIES','M2',wrong),('HIGH_RISK','M2',drug)]
    dump(w/'preflight_cases_frozen.json',{'positive_kind':positive_kind,'cases':[{'case':case,'model_id':model,'question':row} for case,model,row in cases]})
    existing=jl(w/'preflight_results.jsonl');done={(x['case'],x['model_id']) for x in existing};result=list(existing)
    for case,model,row in cases:
        if (case,model) in done:continue
        unload();raw=rt.call(copy.deepcopy(row),model,stage='V6_PREFLIGHT');final=raw['result'];valid=bool(final['validation_status'].get('final_json_valid') or final['validation_status'].get('session_schema_valid'))
        safe=case=='POSITIVE' or (final['answer_status'] in ('INSUFFICIENT_EVIDENCE','VALIDATION_FAILED') and not final['supporting_chunk_ids'])
        item={'case':case,'model_id':model,'api_completed':raw['api_completed'],'raw_json_valid':final['validation_status'].get('raw_json_valid'),'final_schema_valid':valid,'final_status':final['answer_status'],'answer_origin':final['answer_origin'],'negative_gate_safe':safe,'attempt_id':raw['attempt_id'],'raw_record':raw};append(w/'preflight_results.jsonl',item);result.append(item);emit({k:v for k,v in item.items() if k!='raw_record'})
    # Deliberate invalid outputs are offline injection checks, not real model
    # successes or failures and not part of the 720 observations.
    p=copy.deepcopy(positive);payload,evidence=rt.payload(p,'M2');invalid,detail=rt.postprocess(p,'M2','NOT JSON',evidence);malformed_rejected=invalid['answer_status']=='VALIDATION_FAILED'
    fake={'answer':'測試未提供的來源','answer_status':'ANSWERED_PARTIAL','supporting_chunk_ids':['NONEXISTENT'],'evidence':[{'chunk_id':'NONEXISTENT','quote':'不存在的引文','supported_answer_element':'不存在'}],'missing_information':[]};invalid2,detail2=rt.postprocess(p,'M2',json.dumps(fake,ensure_ascii=False),evidence);fabrication_rejected=invalid2['answer_status']=='VALIDATION_FAILED'
    unload()
    hw={'at':now(),'platform':platform.platform(),'python':sys.version,'logical_cpus':psutil.cpu_count(),'physical_cpus':psutil.cpu_count(logical=False),'system_ram_total_bytes':psutil.virtual_memory().total,'ollama_version':requests.get('http://127.0.0.1:11434/api/version',timeout=15).json()}
    gpu=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total,uuid','--format=csv,noheader'],capture_output=True,text=True,timeout=20,creationflags=0x08000000);hw['nvidia_smi_gpu_info']=gpu.stdout if gpu.returncode==0 else None;hw['nvidia_smi_error']=gpu.stderr if gpu.returncode else None;dump(w/'hardware_environment.json',hw)
    summary={'positive_kind':positive_kind,'cases':[{k:v for k,v in x.items() if k!='raw_record'} for x in result],'malformed_json_rejected_offline':malformed_rejected,'invented_citation_rejected_offline':fabrication_rejected,'passed':all(x['api_completed'] and x['final_schema_valid'] and x['negative_gate_safe'] for x in result) and malformed_rejected and fabrication_rejected,'raw_generator_format_failures_are_measured_not_hidden':True,'not_professional_accuracy':True}
    dump(w/'pre_run_e2e_validation.json',summary);assert summary['passed'],'Technical preflight failed; do not run 720'

def verify_freeze(w,check_db=False):
    m=read(w/'frozen_evaluation_manifest.json')
    for x in m['files']:assert sha(x['path'])==x['sha256'],'Frozen input changed: '+x['path']
    if check_db:assert sha(m['corpus']['database'])==m['corpus']['database_sha256']
    return m

def unload():
    for model in requests.get('http://127.0.0.1:11434/api/ps',timeout=20).json().get('models',[]):
        response=requests.post('http://127.0.0.1:11434/api/generate',json={'model':model['name'],'keep_alive':0},timeout=120);response.raise_for_status()

def run():
    w=work();assert read(w/'pre_run_e2e_validation.json')['passed'];verify_freeze(w,True);rt=runtime(w);rows=jl(w/'shared_contexts_180.jsonl');final=w/'generator_final_results_720.jsonl';done={(r['question_id'],r['model_id']) for r in jl(final)};assert len(done)==len(jl(final));options=rt.payload(rows[0],'M2')[0]['options']
    for model in MODEL_SPECS:
        if all((r['question_id'],model) in done for r in rows):continue
        verify_freeze(w,True);unload();warm={'model':MODEL_SPECS[model]['tag'],'prompt':'請只回答ready','stream':False,'keep_alive':'30m','options':{**options,'num_predict':32}}
        start=time.perf_counter();response=requests.post('http://127.0.0.1:11434/api/generate',json=warm,timeout=(30,600));response.raise_for_status();append(w/'warmup_records.jsonl',{'model_id':model,'at':now(),'response':response.json(),'wall_seconds':time.perf_counter()-start,'excluded_from_final_720':True})
        for row in rows:
            key=(row['question_id'],model)
            if key in done:continue
            attempts=[x for x in jl(w/'generator_attempts.jsonl') if x.get('stage')=='V6_FINAL720' and (x['question_id'],x['model_id'])==key]
            completed=next((x for x in reversed(attempts) if x.get('api_completed')),None)
            if completed:g=completed
            else:
                g=attempts[-1] if attempts else None
                for attempt in range(len(attempts)+1,3):
                    g=rt.call(copy.deepcopy(row),model,stage='V6_FINAL720',attempt=attempt)
                    if g['api_completed']:break
            assert g is not None
            g={**g,'canonical_final':True,'context_frozen_before_generation':True}
            assert g['context_digest']==row['context_digest'] and g['context_ids']==[c['chunk_id'] for c in row['top5']]
            append(final,g);done.add(key);dump(w/'checkpoint.json',{'completed':len(done),'target':720,'last_pair':list(key),'at':now(),'resume_safe':True});emit({'stage':'generator','completed':len(done),'model':model,'question_id':key[0],'api_completed':g['api_completed'],'status':g['result']['answer_status'],'origin':g['result']['answer_origin'],'ttft':g.get('ttft_seconds'),'tps':g.get('tps')})
        unload();verify_freeze(w,True)
    assert len(done)==720;emit({'stage':'all_720_complete','completed':len(done)})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['init','references','prepare','preflight','freeze','run']);args=parser.parse_args();{'init':init,'references':revalidate_references,'prepare':prepare,'preflight':preflight,'freeze':freeze,'run':run}[args.stage]()
