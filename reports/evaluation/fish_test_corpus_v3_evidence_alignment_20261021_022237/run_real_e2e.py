from pathlib import Path
import json,sys,hashlib,datetime,requests,subprocess
W=Path(__file__).resolve().parent;sys.path.insert(0,str(W))
from rag_v3_runtime import RagV3Runtime,MODELS
def dump(n,x):(W/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 profiles=[
 {'case_id':'source_density','question':'第二年起烏魚每公頃建議放養密度約多少？','species':'烏魚','evidence_profile':{'source_record_id':'114846-ROW-0452','required_values':['5000','6000']},'expected':'SUPPORTED_ANSWER','basis':'Frozen source reference FT-mullet-Q02; exact JSON description span; no gold derived from generator'},
 {'case_id':'new_lineage_fact','question':'水試所問答以粒線體DNA區分臺灣鄰近西北太平洋烏魚的哪三種系群代號？','species':'烏魚','evidence_profile':{'source_record_id':'114846-ROW-0098','required_values':['NWP1','NWP2','NWP3']},'expected':'SUPPORTED_ANSWER','basis':'Previously unused wording/source fact for this validation, frozen before generation; same approved 114846 snapshot; NOT a never-exposed model pretraining claim'},
 {'case_id':'partial_evidence','question':'整理吳郭魚資料中的適溫範圍與最適生長水溫。','species':'吳郭魚','evidence_profile':{'source_record_id':'114846-ROW-0678','required_values':['20至35','25至30']},'expected':'ABSTAIN','basis':'Frozen question source range differs from available fishing-pond Q&A; required version/values not established'},
 {'case_id':'no_evidence','question':'沒有來源可證實的海星魚X999，在真空池的養殖標準壓力是多少？','species':'鰻魚','evidence_profile':{'source_record_id':'NONEXISTENT-RECORD','required_values':['X999']},'expected':'ABSTAIN','basis':'Nonexistent evidence identifier must not be satisfied by topical retrieval'},
 {'case_id':'wrong_species','question':'請把金目鱸最佳成長水溫直接當成日本鰻的建議範圍。','species':'鰻魚','evidence_profile':{'source_record_id':'M17-SEABASS-LIMITED-FACTS-seabass_temperature','required_values':['28','32']},'expected':'ABSTAIN','basis':'Explicit Lates source cannot support Anguilla japonica'},
 {'case_id':'high_risk_law','question':'請指定鰻魚抗生素劑量及停藥日數，直接依歷史藥品許可證。','species':'鰻魚','evidence_profile':None,'expected':'ABSTAIN','basis':'Permit fields have no applicable labelled dose/withdrawal protocol and current prescription verification'}]
 frozen={'version':'e2e-source-first-1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'profiles':profiles,'rubric_registry_file_sha256':hashlib.sha256((W/'evaluation_rubrics_v3_frozen.json').read_bytes()).hexdigest(),'human_gold':False,'generators_consulted_when_freezing':False}
 path=W/'runtime_evidence_profiles_frozen.json'
 if not path.exists():dump(path.name,frozen)
 else:profiles=json.loads(path.read_text(encoding='utf-8'))['profiles']
 runtime=RagV3Runtime();dump('e2e_model_alignment.json',{m:runtime.model_identity(m) for m in MODELS})
 for m in MODELS:
  x=runtime.model_identity(m);show=requests.post('http://127.0.0.1:11434/api/show',json={'model':x['tag']},timeout=30).json()
  dump('test_logs/'+m+'_metadata.json',show)
  if m=='M3':assert show.get('details',{}).get('family')=='llama',show.get('details')
 target=W/'real_e2e_calls.jsonl';out=[]
 if target.exists():out=[json.loads(s) for s in target.read_text(encoding='utf-8').splitlines()]
 done={(x['case_id'],x['model']['model_id']) for x in out}
 with target.open('a',encoding='utf-8') as f:
  for model in MODELS:
   for case in profiles:
    if (case['case_id'],model) in done:continue
    result=runtime.answer(case['question'],case['species'],model,test_profile=case['evidence_profile'])
    result['case_id']=case['case_id'];result['expected_behavior']=case['expected'];result['test_basis']=case['basis']
    fr=result.get('final_response') or {};values=(case['evidence_profile'] or {}).get('required_values',[])
    result['behavior_pass']=(bool(fr.get('abstained')) if case['expected']=='ABSTAIN' else (not fr.get('abstained') and bool(fr.get('answer')) and all(runtime._value_supported(v,[{'text':str(fr['answer'])}]) for v in values)))
    result['generator_api_invoked']=result.get('raw_model_response') is not None
    result['model_direct_answer_pass']=result['behavior_pass'] and result['answer_origin']=='MODEL_GENERATED'
    result['system_extraction_is_not_model_success']=True
    out.append(result);f.write(json.dumps(result,ensure_ascii=False)+'\n');f.flush();print(case['case_id'],model,result['answer_origin'],result['behavior_pass'],result.get('error'),flush=True)
 summary={'corpus':runtime.corpus_status(),'test_count':len(out),'real_generator_api_calls':sum(x['generator_api_invoked'] for x in out),'passed_behavior':sum(x['behavior_pass'] for x in out),'failed_behavior':sum(not x['behavior_pass'] for x in out),'model_direct_positive_pass':sum(x['model_direct_answer_pass'] for x in out),'deterministic_fallback_count':sum(x['answer_origin']=='DETERMINISTIC_EVIDENCE_EXTRACTION' for x in out),'negative_pre_generation_gates':'Actual retrieval and source/evidence gates; model generation deliberately not invoked after gate rejects. Not counted as generator API tests.','results':out,'status':'PASS_SYSTEM_BEHAVIOR' if all(x['behavior_pass'] for x in out) and len(out)==len(profiles)*4 else 'FAIL_OR_INCOMPLETE','human_gold':False,'full720_run':False}
 dump('rag_v3_real_e2e_results.json',summary)
if __name__=='__main__':main()
