"""Print bounded progress updates while the already-authorized run completes."""
import json,pathlib,time,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
w=pathlib.Path(json.loads((ROOT/'research_staging/unified_rag_v6_evaluation_pointer.json').read_text(encoding='utf-8'))['directory'])
while True:
    p=w/'finalization_status.json'
    try:
        state=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'stage':'unknown'}
        counts={}
        for name in ('judge_quality_detailed.jsonl','logical_accuracy_detailed.jsonl','arithmetic_accuracy_detailed.jsonl','bge_relevance_detailed.jsonl'):
            f=w/name;counts[name]=sum(1 for _ in f.open(encoding='utf-8')) if f.exists() else 0
        print(json.dumps({'at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'finalization':state,'metric_rows':counts},ensure_ascii=False),flush=True)
        if state.get('status')=='FAILED' or state.get('stage')=='ALL_COMPLETE':break
    except (OSError,ValueError) as exc:print(json.dumps({'temporary_monitor_read_error':str(exc)}),flush=True)
    time.sleep(50)
