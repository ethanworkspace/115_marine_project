"""Native CI capture with validated UTC-Z filters; prior capture diagnostics retained."""
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

def utc_z(value):
    return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

def query(start,end):
    expr=f"*[System[TimeCreated[@SystemTime>='{utc_z(start)}' and @SystemTime<='{utc_z(end)}']]]"
    p=subprocess.run(['wevtutil.exe','qe','Microsoft-Windows-CodeIntegrity/Operational','/q:'+expr,
        '/rd:true','/c:2000','/f:xml'],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
    if p.returncode:raise RuntimeError(p.stderr)
    root=ET.fromstring('<Events>'+p.stdout+'</Events>');ns={'e':'http://schemas.microsoft.com/win/2004/08/events/event'};rows=[]
    for ev in root:
        s=ev.find('e:System',ns)
        rows.append(parse_event(dict(event_id=int(s.find('e:EventID',ns).text),
            record_id=int(s.find('e:EventRecordID',ns).text),provider=s.find('e:Provider',ns).attrib['Name'],
            raw_event_xml=ET.tostring(ev,encoding='unicode'),message=None)))
    return rows,expr

def capture(point,start,end):
    error=None;events=[];expr=None
    try:events,expr=query(start,end)
    except Exception as exc:error=str(exc)
    blocks=[r for r in events if r['event_id'] in (3033,3077) and any(s in
        (str(r.get('blocked_path'))+' '+str(r.get('event_data'))).casefold() for s in
        ('.venv-reranker','torch\\lib','python314','bge-reranker'))]
    r=dict(point=point,start_utc=utc_z(start),end_utc=utc_z(end),status='unavailable' if error else 'collected',
        count=len(events),relevant_execution_block_count=len(blocks),events=events,error=error,
        query=expr,capped=len(events)==2000,read_only=True,collector='Windows native wevtutil UTC-Z v2',
        supersedes_for_analysis='Earlier +00:00 native time filter returned false empty positive control; records remain preserved')
    append_jsonl(OUT/'code_integrity_native_monitor_v2.jsonl',r)
    return r

def main():
    if (OUT/'code_integrity_native_monitor_v2.jsonl').exists():raise SystemExit('Evidence exists; refuse overwrite')
    control,expr=query('2026-10-07T07:01:00+00:00','2026-10-07T07:02:00+00:00')
    with (OUT/'native_query_positive_control_z.json').open('x',encoding='utf-8') as f:
        json.dump(dict(query=expr,event_count=len(control),events=control,
            passed=len(control)>0,excluded_from_benchmark_counts=True),f,indent=2)
    if not control:raise SystemExit('Native positive control failed; do not call empty results no events')
    seen=set();live_cursor=json.loads((OUT/'execution_start.json').read_text())['timestamp'];next_live=time.monotonic()
    while True:
        for line in (OUT/'code_integrity_monitor.jsonl').read_text(encoding='utf-8').splitlines():
            try:r=json.loads(line)
            except json.JSONDecodeError:continue
            if r['point'] in seen:continue
            value=capture(r['point'],r['start_utc'],r['end_utc']);seen.add(r['point'])
            print(json.dumps({k:value[k] for k in ('point','count','status','relevant_execution_block_count')}),flush=True)
            if r['point']=='benchmark_end':return
        if time.monotonic()>=next_live:
            end=dt.datetime.now(dt.timezone.utc).isoformat()
            value=capture('live_'+end,live_cursor,end);live_cursor=end;next_live=time.monotonic()+30
            if value['relevant_execution_block_count']:print('ATTENTION: related enforced block observed',flush=True)
        time.sleep(2)

if __name__=='__main__':main()
