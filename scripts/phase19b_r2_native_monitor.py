"""Read-only native CI companion; preserve PowerShell capture failures separately."""
import datetime as dt
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.runner import append_jsonl
from src.evaluation.edge.recovery19b1 import parse_event
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'
seen=set()

def capture(point,start,end):
    query=f"*[System[TimeCreated[@SystemTime>='{start}' and @SystemTime<='{end}']]]"
    p=subprocess.run(['wevtutil.exe','qe','Microsoft-Windows-CodeIntegrity/Operational',
        '/q:'+query,'/rd:true','/c:2000','/f:xml'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
    rows=[];error=None
    try:
        if p.returncode:raise RuntimeError(p.stderr)
        root=ET.fromstring('<Events>'+p.stdout+'</Events>');ns={'e':'http://schemas.microsoft.com/win/2004/08/events/event'}
        for ev in root:
            system=ev.find('e:System',ns)
            row=dict(event_id=int(system.find('e:EventID',ns).text),record_id=int(system.find('e:EventRecordID',ns).text),
                provider=system.find('e:Provider',ns).attrib['Name'],raw_event_xml=ET.tostring(ev,encoding='unicode'),message=None)
            rows.append(parse_event(row))
    except Exception as exc:error=str(exc)
    relevant=[r for r in rows if r['event_id'] in (3033,3077) and any(s in
        (str(r.get('blocked_path'))+' '+str(r.get('event_data'))).casefold() for s in ('.venv-reranker','torch\\lib','python314','bge-reranker'))]
    value=dict(point=point,start_utc=start,end_utc=end,status='unavailable' if error else 'collected',
        count=len(rows),relevant_execution_block_count=len(relevant),events=rows,error=error,
        capped=len(rows)==2000,read_only=True,collector='Windows native wevtutil',
        supplements='code_integrity_monitor.jsonl PowerShell module unavailable; original records retained')
    append_jsonl(OUT/'code_integrity_native_monitor.jsonl',value)
    return value

def main():
    if (OUT/'code_integrity_native_monitor.jsonl').exists():raise SystemExit('Companion evidence exists; refuse overwrite')
    while True:
        path=OUT/'code_integrity_monitor.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:r=json.loads(line)
                except json.JSONDecodeError:continue
                if r['point'] in seen:continue
                value=capture(r['point'],r['start_utc'],r['end_utc']);seen.add(r['point'])
                print(json.dumps({k:value[k] for k in ('point','status','count','relevant_execution_block_count')}),flush=True)
                if r['point']=='benchmark_end':return
        time.sleep(2)

if __name__=='__main__':main()
