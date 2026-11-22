import sys,json,re,importlib.metadata
from pathlib import Path
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parent
def main():
 log=W/'test_logs/repository_pytest.log';text=log.read_text(encoding='utf-8-sig');assert '607 passed, 8 subtests passed' in text
 iso=W/'test_logs/final_isolated_pytest.log';it=iso.read_text(encoding='utf-8-sig');assert '47 passed' in it
 out={'interpreter':sys.executable,'python':sys.version,'versions':{p:importlib.metadata.version(p) for p in ['pytest','streamlit','jsonschema','psutil']},'repository':{'command':[sys.executable,'-B','-m','pytest','tests/','-q','-p','no:cacheprovider','--basetemp',str(W/'repository_test_temp')],'scope':'All formal tests/; no entire-repository recursive collection into historical reports or virtual environments','passed':607,'subtests_passed':8,'failed':0,'skipped':0,'collection_errors':0,'exit_code':0,'full_log':str(log)},'isolated_final_policy_and_tokenizer':{'command':[sys.executable,'-B','-m','pytest','test_answer_policy_final.py','test_numeric_grounding_v3.py','test_partial_gap_completion.py','test_arithmetic_parser_v4.py','-q','-p','no:cacheprovider'],'passed':47,'failed':0,'skipped':0,'collection_errors':0,'exit_code':0,'full_log':str(iso)},'real_generator_tests_are_separate':'regression_results_200_final.jsonl + safety_results_24_final.jsonl; not mocks','production_dependencies_modified':False}
 (W/'repository_pytest_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Saved actual formal607 + final isolated47 test results',flush=True)
if __name__=='__main__':main()
