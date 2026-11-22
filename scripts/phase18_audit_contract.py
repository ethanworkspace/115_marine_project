"""Preserve v1 diagnostic snapshots; derive v2 structural-only exclusions."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.evaluation.validity.runner import OUT,write_json,write_jsonl
from src.evaluation.validity.core import structural_only,digest
from src.evaluation.validity.runtime import AUDIT_PROMPT,AUDIT_OUTPUT_CONTRACT_V2
from src.evaluation.generation.frozen import read_jsonl,sha256_file

target=OUT/'audit_execution_protocol_v2.json'
if target.exists():raise SystemExit('Refusing to overwrite frozen audit v2 contract')
records=read_jsonl(OUT/'blind_audit_records.jsonl')
excluded=[]
for r in records:
    eligible=[]
    for c in r['claims']:
        reason=structural_only(c)
        if reason:excluded.append({**c,'exclusion_reason':reason})
        else:eligible.append(c)
    r['claims']=eligible
write_jsonl(OUT/'blind_audit_records_v2.jsonl',records)
write_jsonl(OUT/'structural_exclusions_v2.jsonl',excluded)
write_json(target,{'version':'phase18_blind_audit_contract_v2',
    'parent_manifest_sha256':sha256_file(OUT/'experiment_manifest.json'),
    'generator_outputs_modified':False,'sample_output_ids_unchanged':True,
    'judge_model_changed':False,'judge_options_changed':False,'entailment_definitions_changed':False,
    'technical_changes':['Structural-only list markers and citation-ID lines excluded from factual claim denominator',
        'Output schema includes quote maxLength=240 and reason maxLength=160; schema made explicit to judge'],
    'initial_diagnostics':'initial_diagnostics_v1; retained, excluded from main v2 analysis',
    'in_flight_initial_request':'unknown result; explicit capture limitation retained',
    'claims_before':sum(1 for _ in read_jsonl(OUT/'claims.jsonl')),
    'claims_for_audit':sum(len(r['claims']) for r in records),'structural_exclusions':len(excluded),
    'prompt_sha256':digest(AUDIT_PROMPT+'\n'+AUDIT_OUTPUT_CONTRACT_V2),
    'sample_sha256':{n:sha256_file(OUT/n) for n in ['blind_audit_records_v2.jsonl','structural_exclusions_v2.jsonl']}})
print(json.dumps({'claims':sum(len(r['claims']) for r in records),'structural_exclusions':len(excluded)}),flush=True)
