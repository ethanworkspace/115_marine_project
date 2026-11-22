"""Historical positive control, excluded from benchmark event counts."""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
q="*[System[TimeCreated[@SystemTime>='2026-10-07T07:01:00+00:00' and @SystemTime<='2026-10-07T07:02:00+00:00']]]"
p=subprocess.run(['wevtutil.exe','qe','Microsoft-Windows-CodeIntegrity/Operational','/q:'+q,'/f:xml','/c:2000'],
    capture_output=True,encoding='utf-8',errors='replace')
r=dict(returncode=p.returncode,query=q,event_count=len(ET.fromstring('<Events>'+p.stdout+'</Events>')) if p.returncode==0 else None,
    raw_xml=p.stdout,stderr=p.stderr,scope='Historical positive-control query only; excluded from benchmark new-event counts')
with (ROOT/'reports/evaluation/edge/phase19B_exec_r2/native_query_positive_control.json').open('x',encoding='utf-8') as f:json.dump(r,f,indent=2)
print(json.dumps({k:v for k,v in r.items() if k not in ('raw_xml','stderr')}))
