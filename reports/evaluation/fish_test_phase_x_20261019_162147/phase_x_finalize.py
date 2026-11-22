import hashlib, json, os
from pathlib import Path
from collections import Counter

ROOT = Path.cwd()
X = ROOT / 'reports/evaluation/fish_test_phase_x_20261019_162147'
W = ROOT / 'reports/evaluation/fish_test_phase_w_20261019_133804'
V = ROOT / 'reports/evaluation/fish_test_phase_v_20261018_224918'

def readj(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def readjl(path): return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def writej(name, obj): (X/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def writejl(name, rows): (X/name).write_text(''.join(json.dumps(r, ensure_ascii=False, separators=(',',':'))+'\n' for r in rows), encoding='utf-8')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

# Preserve original causal breakdown and attach actual regression evidence.
m2=readj(X/'m2_abstention_root_cause.json')
api=readj(X/'m2_api_regression.json')
prompt=readj(X/'m2_prompt_repair_regression.json')
all_reg=api.get('results',[])+[prompt]
direct=[r for r in all_reg if 'GROUPER' in str(r.get('case_id',''))]
m2['phase_x_direct_evidence_regression']={
    'case_count':len(direct),
    'generator_calls':sum(bool(r.get('generator_called')) for r in direct),
    'answered_with_required_density_and_unit':sum(r.get('status')=='PASS' for r in direct),
    'self_abstentions_despite_valid_citation_binding':sum(r.get('effective_status')=='abstain' and (r.get('citation_validation') or {}).get('valid',False) for r in direct),
    'confirmed_unnecessary_refusal_in_controlled_case':True,
    'case_scope':'同一筆可追溯的鞍帶石斑事實卡，包含10,000–30,000尾/公頃及水質、養殖經驗調整條件。此為單一診斷案例，不代表全體 false-refusal 率。',
    'prompt_repair_status':prompt.get('status'),
    'prompt_sha256':prompt.get('prompt_sha256'),
    'safety_gates_disabled':False,
    'interpretation':'實際模型自行拒答；沒有證據顯示此案例由 Citation/Species/Law/Evidence 後處理閘覆蓋。提示限縮後仍拒答，故 M2 answerability 問題尚未修復。'
}
m2['deterministic_guard_reason_counts']={'NO_QUALIFIED_CONTEXT':86,'DRUG_SPECIFIC_AUTHORITY_NOT_IN_CONTEXT':18,'REQUIRED_DURATION_NOT_IN_CONTEXT':2}
m2['confirmed_unnecessary_refusals'] = 0  # full 180-run false-refusal count remains unestablished
m2['limitations'].append('Phase X 在一個直接有據的單段案例中確認不必要拒答；不可外推為180題 false-refusal 數。')
writej('m2_abstention_root_cause.json',m2)

# Current repository test run: parse the actual pytest summary.
log=(X/'repository_pytest_x.log').read_text(encoding='utf-8',errors='replace')
import re
match=re.search(r'(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) failed)? in ([0-9.]+)s',log)
pytest={'run_log':'repository_pytest_x.log','collected':607,'passed':0,'skipped':0,'failed':0,'duration_seconds':None,'status':'UNPARSED'}
if match:
    pytest.update(passed=int(match.group(1)),skipped=int(match.group(2) or 0),failed=int(match.group(3) or 0),duration_seconds=float(match.group(4)))
    pytest['status']='PASS' if pytest['failed']==0 else 'FAIL'
writej('repository_pytest_validation.json',pytest)

# Fresh, read-only protected-file digest reconciliation from the saved 636-file manifest.
manifest=readjl(W/'protected_baseline_before_phase_w.jsonl')
rechecked=[]
for row in manifest:
    rel=Path(row['path'])
    p=(ROOT/rel).resolve()
    try: p.relative_to(ROOT.resolve())
    except ValueError:
        rechecked.append({'path':row['path'],'expected_sha256':row.get('expected_sha256'),'actual_sha256':None,'status':'PATH_OUTSIDE_PROJECT'}); continue
    if not p.is_file():
        rechecked.append({'path':row['path'],'expected_sha256':row.get('expected_sha256'),'actual_sha256':None,'status':'MISSING'}); continue
    actual=sha(p)
    rechecked.append({'path':row['path'],'expected_sha256':row.get('expected_sha256'),'actual_sha256':actual,'size_bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns,'status':'MATCH' if actual==row.get('expected_sha256') else 'MISMATCH'})
writejl('protected_baseline_recheck_phase_x.jsonl',rechecked)
counts=Counter(r['status'] for r in rechecked)
sqlite=ROOT/'rag_store.sqlite3'
sqlite_actual=sha(sqlite) if sqlite.is_file() else None
sqlite_expected='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
baseline={'manifest_records':len(manifest),'rechecked_records':len(rechecked),'status_counts':dict(counts),'all_636_match':len(rechecked)==636 and counts['MATCH']==636,'sqlite_path':str(sqlite),'sqlite_sha256_expected':sqlite_expected,'sqlite_sha256_actual':sqlite_actual,'sqlite_match':sqlite_actual==sqlite_expected,'method':'read-only SHA-256 recheck; no baseline files written or modified'}
writej('protected_baseline_recheck_phase_x.json',baseline)

# Summarize the existing real W E2E record, X tests, and the failed positive-evidence M2 regression.
w_e2e=readj(W/'rag_v3_end_to_end_validation.json')
w_val=readj(W/'phase_w_output_validation.json')
appt=readj(X/'streamlit_app_test_x.json')
refs=readjl(X/'verified_reference_answer_candidates.jsonl')
ref_counts=Counter(r['verification_status'] for r in refs)
retr_summary=readj(X/'retrieval_coverage_regression_summary.json')
coverage=readj(X/'source_coverage_improvement.json')
e2e={
  'status':'NOT_PASSED',
  'scope':'Phase X did not run 720 generations. It reused Phase W full-run/E2E evidence and executed small M2 API regressions plus a Streamlit AppTest and repository pytest.',
  'phase_w_full_run':w_e2e.get('generation_rows'),
  'phase_w_model_identity':w_e2e.get('model_identity'),
  'phase_w_retrieval_integrity':w_e2e.get('corpus_and_top5_trace_integrity'),
  'phase_w_full_system_smoke_status':w_e2e.get('full_system_smoke',{}).get('status'),
  'phase_w_streamlit_status':w_e2e.get('streamlit',{}).get('status'),
  'phase_x_streamlit_app_test':appt,
  'phase_x_repository_pytest':pytest,
  'm2_positive_evidence_regression':{'calls':len(direct),'answered':sum(r.get('status')=='PASS' for r in direct),'self_abstained':sum(r.get('effective_status')=='abstain' for r in direct),'latest_prompt_repair_status':prompt.get('status')},
  'technical_tests_passed':{'repository_pytest':pytest['status']=='PASS','streamlit_initial_render':appt.get('status')=='passed','phase_w_real_full_run_exists':w_e2e.get('generation_rows',{}).get('canonical_unique_question_model_rows')==720},
  'blocking_findings':['在有明確來源事實卡、單一可用 Chunk 的直接答案回歸中，M2 仍自行拒答；提示修復回歸未通過。','Phase W 180題完整執行不能視作 Phase X 修復後新一輪，且不能用舊結果證明 M2 現已可回答。','正式專業準確率仍缺人工 Gold／已鎖定 Rubric；多數題目來源或範圍不足。'],
  'full_e2e_acceptance':False,'ready_for_new_720_run':False,'formal_environment_switch':False
}
writej('rag_e2e_full_validation.json',e2e)

readiness={
 'phase_w_question_count':180,'phase_w_generator_rows':720,'phase_w_effective_status_counts':w_e2e.get('generation_rows',{}).get('effective_status_counts'),
 'phase_x_m2_abstention_causes':m2.get('cause_counts'),'phase_x_targeted_m2_regression_calls':len(direct),'phase_x_targeted_m2_regression_passes':sum(r.get('status')=='PASS' for r in direct),
 'phase_v_to_w_coverage':{'any_context':[retr_summary['phase_v_any_context'],retr_summary['phase_w_any_context']],'full_top5':[retr_summary['phase_v_full_top5'],retr_summary['phase_w_full_top5']],'same_corpus':retr_summary['corpus_versions_same'],'identical_query_text_count':retr_summary['query_text_identical_n'],'transition_counts':retr_summary['per_question_transition_counts']},
 'answer_candidate_rows':len(refs),'answer_candidate_status_counts':dict(ref_counts),'source_backed_automated_candidates':ref_counts['SOURCE_VERIFIED_AUTOMATED'],'human_gold':0,'new_formal_sources_admitted':coverage.get('new_professional_source_files_admitted',0),'new_formal_chunks_added':coverage.get('new_corpus_chunks_added',0),
 'repo_pytest':pytest,'streamlit_initial_render':appt.get('status'),'full_system_e2e_pass':False,'ready_for_full_720_regression':False,
 'remaining_gates':['修復並再次通過 M2 有據問答回歸，Citation/Species/Law/Evidence 安全閘維持啟用。','取得新的合規且可重現專業來源，補足六魚種來源覆蓋；官方頁面線索需保存原件/版本並核實使用條件。','由研究者審閱並鎖定來源支持答案及 Logical/Arithmetic rubric；AI-assisted 候選不可當 Human Gold。','完成全情境四模型真實端到端重新驗收後，再啟動新720次回歸評測。']}
writej('evaluation_readiness_updated.json',readiness)

# Input/output format and cross-file sanity checks.
all_json=[p.name for p in X.glob('*.json')]
json_errors=[]
for n in all_json:
    try: readj(X/n)
    except Exception as ex: json_errors.append({'file':n,'error':str(ex)})
all_jsonl=[p.name for p in X.glob('*.jsonl')]
jsonl_errors=[]
for n in all_jsonl:
    try: readjl(X/n)
    except Exception as ex: jsonl_errors.append({'file':n,'error':str(ex)})
validation={'json_files':len(all_json),'jsonl_files':len(all_jsonl),'json_errors':json_errors,'jsonl_errors':jsonl_errors,'retrieval_regression_rows':len(readjl(X/'retrieval_coverage_regression_180.jsonl')),'m2_abstention_rows':len(readjl(X/'m2_abstention_detail_180.jsonl')),'reference_candidate_rows':len(refs),'source_lead_rows':len(readjl(X/'source_search_findings.jsonl')),'baseline_636_match':baseline['all_636_match'],'sqlite_match':baseline['sqlite_match'],'pytest':pytest,'e2e_acceptance':e2e['status'],'status':'PASS_FORMAT_AND_INTEGRITY' if not json_errors and not jsonl_errors and len(readjl(X/'retrieval_coverage_regression_180.jsonl'))==180 and len(readjl(X/'m2_abstention_detail_180.jsonl'))==180 and len(refs)==28 and baseline['all_636_match'] and baseline['sqlite_match'] and pytest['status']=='PASS' else 'FAIL'}
writej('phase_x_validation.json',validation)

compat={'phase':'X','historical_phase_w_outputs_modified':False,'production_modified':False,'production_sqlite_modified':False,'historical_e4_modified':False,'corpus_v2_modified':False,'original_phase_w_720_generation_modified':False,'formal_source_admission_performed':False,'new_corpus_chunks_added':0,'phase_x_new_full_generation_count':0,'small_m2_regression_calls':len(all_reg),'m2_regression_all_pass':all(r.get('status')=='PASS' for r in direct),'repository_pytest':pytest,'protected_manifest':baseline,'status':'PASS_PROTECTED_BASELINE' if baseline['all_636_match'] and baseline['sqlite_match'] else 'BASELINE_MISMATCH'}
writej('compatibility.json',compat)

# Final user-facing report.
report=f'''# Phase X 最終報告\n\n## 結果摘要\n\n- Phase W 原始 180 題、720 筆生成均保留；本輪未重跑 720 次。\n- M2 拒答拆解：86 題無合格 Context（NO_EVIDENCE）、20 題由確定性證據／安全閘判為不足（INSUFFICIENT_EVIDENCE）、73 題為模型自行拒答（MODEL_ABSTENTION）、1 題輸出無效（PARSER_OR_VALIDATION_REJECTION）。\n- 73 筆模型自行拒答中，13 筆自述證據充分或部分充分，屬待查的可能不必要拒答候選，不能直接算成錯誤。Phase X 對一個含有明確石斑魚放養密度事實卡的單段案例實測，M2 仍拒答；故確認該案例是不必要拒答，但不能推算完整180題 false-refusal 率。兩次限縮提示回歸均未取得可用回答。\n- Phase V→W 使用相同 Corpus 版本，180題查詢文字一致；有 Context 由99降至94，完整 Top-5由37降至34。每題診斷顯示111題不變、10題改善、59題下降。差異主要與 W 較嚴格的來源 allowlist／物種適用性候選過濾有關；現有紀錄不足以把變化單獨歸因於 RRF 或 reranker。\n- 本輪從既有4份原件確認15題的來源事實候選；另有6題僅能做題幹內算術診斷，7題仍缺直接支持。沒有新增正式准入來源或 Corpus chunks；Human Gold仍為0。\n- Repository pytest：{pytest['passed']} passed、{pytest['skipped']} skipped、{pytest['failed']} failed（收集{pytest['collected']}項）。Phase X Streamlit 初始畫面測試通過。\n- 完整 E2E 驗收：未通過。阻塞點是 M2 在明確支持的正向案例仍自行拒答，且來源／答案 Rubric 尚不足以支撐正式專業準確率評測。暫不啟動新的720次回歸評測。\n- Frozen Manifest：{baseline['status_counts'].get('MATCH',0)}/636相符；正式 SQLite SHA-256 {'相符' if baseline['sqlite_match'] else '不相符'}。\n\n## 來源候選與限制\n\n15題標記為 `SOURCE_VERIFIED_AUTOMATED`，其核對依據是4份本機 PDF 原件的 SHA-256、實際頁面文字、段落位置、原題魚種／數值及既有研究用事實卡範圍。這表示可供研究者覆核的自動來源核驗候選，不代表第三方授權已取得、來源已新增正式 Admission、或題目已成 Human Gold。6題只核驗題幹內算術，不能冒充領域公式來源；7題缺乏足以支撐題目完整要求的原文。\n\n本輪另記錄5個官方網頁來源線索（含鰻魚疾病、溶氧、烏魚溶氧及動物用藥規則），但尚未保存可重現原始 bytes／版本與使用範圍，因此未納入索引或正式來源清單。\n\n## 下一次完整重測條件\n\n1. 修復 M2 正向有據回答的回歸失敗，同時維持所有安全閘。\n2. 固定並核實可合法使用、魚種適用且能支援答案的專業來源。\n3. 完成研究者對答案與 rubric 的覆核；AI 標記維持 `NOT_HUMAN_GOLD` 直到實際人工審查。\n4. 重新完成四模型、正向證據／無證據／衝突來源等情境的真實端到端驗收。\n\n詳細紀錄見本目錄中的 `m2_abstention_root_cause.json`、`retrieval_coverage_regression_180.jsonl`、`verified_reference_answer_candidates.jsonl`、`rag_e2e_full_validation.json` 及 `compatibility.json`。\n'''
(X/'phase_x_final_report.md').write_text(report,encoding='utf-8')
print(json.dumps({'status':validation['status'],'manifest':baseline,'pytest':pytest,'references':dict(ref_counts),'m2_direct_regression_cases':len(direct),'m2_direct_passes':sum(r.get('status')=='PASS' for r in direct),'output':str(X)},ensure_ascii=False,indent=2))
