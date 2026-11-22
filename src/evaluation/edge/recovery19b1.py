"""Evidence-based application-control diagnostics and strict recovery gates."""
from __future__ import annotations
import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

MODEL_ID='BAAI/bge-reranker-v2-m3'
REVISION='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
FORBIDDEN_ACTIONS={'disable_smart_app_control','disable_defender','disable_WDAC','disable_AppLocker',
    'disable_code_integrity','policy_allow_rule','remove_Zone_Identifier','modify_failed_runtime',
    'CPU_fallback','replace_model','change_reranker_revision','random_package_trial'}


def remediation_allowed(actions):
    allowed={'read_events','capture_file_identity','capture_hashes','minimal_import','run_frozen_gates','read_metadata'}
    return set(actions).issubset(allowed)


def parse_event(row):
    ns={'e':'http://schemas.microsoft.com/win/2004/08/events/event'}
    root=ET.fromstring(row['raw_event_xml'])
    data={d.attrib.get('Name',''):d.text for d in root.findall('e:EventData/e:Data',ns)}
    system=root.find('e:System',ns)
    cor=system.find('e:Correlation',ns)
    stamp=system.find('e:TimeCreated',ns).attrib['SystemTime']
    return {**row,'timestamp':stamp,'event_data':data,
        'correlation_id':cor.attrib.get('ActivityID') if cor is not None else None,
        'blocked_path':data.get('File Name') or data.get('FileNameBuffer'),
        'policy_identifier':data.get('PolicyGUID') or data.get('PolicyID'),
        'policy_name':data.get('PolicyName'), 'status_code':data.get('Status')}


def relevant_block_events(rows):
    return [r for r in rows if r['event_id'] in (3033,3077) and '.venv-reranker' in
            str(r.get('blocked_path','')).casefold()]


def classify(events, *, runtime_drift=False, signature_status=None, zone_present=None):
    classifications=[]
    blocks=relevant_block_events(events)
    if any(r['event_id']==3077 for r in blocks):classifications.append('application_policy_block')
    if blocks and signature_status=='NotSigned':classifications.append('signature_trust_failure')
    if runtime_drift:classifications.append('runtime_artifact_drift')
    # Zone presence alone cannot establish causality; policy history changes require separate evidence.
    return classifications or ['unknown']


def exact_model_identity(manifest, files):
    return manifest.get('model_id')==MODEL_ID and manifest.get('revision')==REVISION and all(
        files.get(k)==v['sha256'] for k,v in manifest['files'].items())


def compatibility(reference, actual):
    ref_ids=[r['chunk_id'] for r in sorted(reference,key=lambda r:int(r['reranker_rank']))]
    act_ids=[r['chunk_id'] for r in sorted(actual,key=lambda r:int(r['reranker_rank']))]
    ref_scores={r['chunk_id']:float(r['reranker_score']) for r in reference}
    ids_equal=set(ref_ids)==set(act_ids) and len(ref_ids)==len(act_ids)
    deltas=[abs(float(r['reranker_score'])-ref_scores[r['chunk_id']]) for r in actual if r['chunk_id'] in ref_scores]
    return dict(candidate_identity_preserved=ids_equal,ordering_equal=ref_ids==act_ids,
        all_scores_finite=all(math.isfinite(float(r['reranker_score'])) for r in actual),
        max_score_difference=max(deltas) if deltas else None,score_exact=ids_equal and all(d==0 for d in deltas),
        passed=ids_equal and ref_ids==act_ids and all(math.isfinite(float(r['reranker_score'])) for r in actual))


def resume_gate(gates):
    return all(gates.get(k,{}).get('passed') is True for k in ('R0','R1','R2','R3','R4','R5','E4_60'))


def pe_imports(path):
    """Static PE imports/delay imports only. Does not invoke Windows loader or change PATH."""
    data=Path(path).read_bytes()
    if data[:2]!=b'MZ':raise ValueError('Not a PE image')
    offset=struct.unpack_from('<I',data,0x3c)[0]
    if data[offset:offset+4]!=b'PE\0\0':raise ValueError('Invalid PE signature')
    count=struct.unpack_from('<H',data,offset+6)[0]
    opt_len=struct.unpack_from('<H',data,offset+20)[0]
    opt=offset+24;magic=struct.unpack_from('<H',data,opt)[0]
    if magic not in (0x10b,0x20b):raise ValueError('Unsupported PE optional header')
    directory=opt+(112 if magic==0x20b else 96)
    sections=[]
    for i in range(count):
        s=opt+opt_len+i*40
        virtual_size,va,rawsize,raw=struct.unpack_from('<IIII',data,s+8)
        sections.append((va,max(virtual_size,rawsize),raw))
    def pos(rva):
        for va,size,raw in sections:
            if va<=rva<va+size:return raw+rva-va
        if rva<len(data):return rva
        raise ValueError('RVA outside PE file')
    def string(rva):
        p=pos(rva);end=data.find(b'\0',p)
        return data[p:end].decode('ascii')
    result={'machine_hex':hex(struct.unpack_from('<H',data,offset+4)[0]),'imports':[],'delay_imports':[]}
    rva,size=struct.unpack_from('<II',data,directory+8)
    if rva:
        p=pos(rva)
        for _ in range(min(size//20+1,4096)):
            fields=struct.unpack_from('<IIIII',data,p)
            if not any(fields):break
            result['imports'].append(string(fields[3]));p+=20
    rva,size=struct.unpack_from('<II',data,directory+13*8)
    if rva:
        p=pos(rva)
        for _ in range(min(size//32+1,4096)):
            fields=struct.unpack_from('<IIIIIIII',data,p)
            if not any(fields):break
            if fields[0]&1:result['delay_imports'].append(string(fields[1]))
            else:result.setdefault('limitations',[]).append('Legacy absolute delay-import addressing not interpreted')
            p+=32
    return result
