"""Record real tests and retained result integrity before publishing main."""
import hashlib,json,re,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'research_staging/maintenance/cleanup_publish_20261122'
DOC=ROOT/'docs/research_results'
WORK=Path(json.loads((ROOT/'research_staging/streamlit_cloud_deployment_pointer.json').read_text(encoding='utf-8'))['directory'])

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

xml=ET.parse(OUT/'repository_pytest.xml').getroot()
suites=list(xml.iter('testsuite'))
counts={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','errors','failures','skipped')}
log=(OUT/'repository_pytest.log').read_text(encoding='utf-8')
passed=int(re.search(r'(\d+) passed',log).group(1))
subtests=int(re.search(r'(\d+) subtests passed',log).group(1))
assert counts['errors']==counts['failures']==counts['skipped']==0
assert counts['tests']==passed+subtests
runtime='reports/evaluation/fish_test_corpus_v3_evidence_alignment_20261021_022237/test_env/Scripts/python.exe'
code="import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version,'packages':{n:m.version(n) for n in ('pytest','PyMuPDF','python-docx','jsonschema','requests','torch','transformers')}}))"
env=json.loads(subprocess.check_output([str(ROOT/runtime),'-B','-c',code],cwd=ROOT,text=True,encoding='utf-8'))
result={'status':'PASS','scope':'Actual original local tests/ with required private fixtures and configured research environment; not a clean-public-clone claim.',
        'passed':passed,'subtests_passed':subtests,'failed':counts['failures'],'errors':counts['errors'],'skipped':counts['skipped'],
        'junit_cases_including_subtests':counts['tests'],'interpreter':runtime,'environment':env,
        'command':'python -B -m pytest tests -q -p no:cacheprovider --basetemp <isolated-maintenance>/pytest_tmp --junitxml=<isolated-maintenance>/repository_pytest.xml',
        'no_model_generation':True,'no_production_environment_changes':True}
(OUT/'repository_pytest_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(DOC/'repository_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
manifest=json.loads((ROOT/'reports/evaluation/unified_rag_v6_evaluation_20261121_164940/result_artifact_manifest.json').read_text(encoding='utf-8'))
critical={'generator_raw_attempts_720.jsonl','generator_final_results_720.jsonl','shared_contexts_180.jsonl','questions_original_180.jsonl'}
retained=[]
for r in manifest['files']:
    p=Path(r['path'])
    if p.name in critical:
        retained.append({'path':str(p.relative_to(ROOT)),'matches_recorded_sha256':sha(p)==r['sha256']})
assert len(retained)==4 and all(r['matches_recorded_sha256'] for r in retained)
assert requests.get('http://127.0.0.1:8765/health',timeout=10).json()['status']=='ok'
compat=json.loads((WORK/'reports/compatibility.json').read_text(encoding='utf-8'))
assert compat['unchanged']==636 and compat['baseline_matches']
summary={'status':'PASS','protected_files':636,'protected_unchanged':636,
         'production_sqlite_sha256':compat['production_sqlite_sha256'],'active_corpus_sha256':compat['active_corpus_sha256'],
         'critical_latest_run_files':retained,'backend_health_after_cleanup':'ok','historical_data_and_results_not_moved':True,
         'cache_permission_errors_left_untouched':True}
(OUT/'compatibility.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tests':result['passed'],'subtests':subtests,'protected_unchanged':636,'retained_latest_run_files':len(retained),'backend_health':'ok'},ensure_ascii=False))
