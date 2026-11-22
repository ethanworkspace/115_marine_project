"""Manual crash recovery for THIS run only. Never run while a generator/scorer is active.

Preserve a torn journal byte-for-byte, keep all complete records, and resume using
frozen_runner.py. No source, prompt, corpus, safety gate or completed result changes.
"""
from pathlib import Path
import json,datetime,sys,os
W=Path(__file__).resolve().parent
def recover(name):
 p=W/name
 if not p.exists():return {'file':name,'status':'ABSENT'}
 raw=p.read_bytes();lines=raw.splitlines(keepends=True);valid=[];bad=[]
 for i,line in enumerate(lines):
  if not line.strip():continue
  try:json.loads(line)
  except Exception as exc:
   if i!=len(lines)-1:raise RuntimeError(f'Nonterminal corrupt record at {name}:{i+1}; requires diagnosis, no automatic rewrite') from exc
   bad.append({'line':i+1,'error':str(exc)})
  else:valid.append(line.rstrip(b'\r\n')+b'\n')
 if not bad:return {'file':name,'status':'VALID','records':len(valid)}
 stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S');backup=W/f'{name}.crash_bytes_{stamp}.bin';backup.write_bytes(raw)
 p.write_bytes(b''.join(valid));return {'file':name,'status':'TORN_LAST_RECORD_QUARANTINED','complete_records':len(valid),'backup':str(backup),'bad':bad}
if __name__=='__main__':
 import psutil
 for proc in psutil.process_iter(['pid','cmdline']):
  if proc.pid==os.getpid():continue
  try:cmd=' '.join(proc.info['cmdline'] or [])
  except Exception:continue
  if 'frozen_runner.py' in cmd or 'score_frozen_run.py' in cmd:raise SystemExit('Refusing recovery while an evaluation process is active')
 out=[recover(n) for n in ['generator_raw_attempts_720.jsonl','generator_final_results_720.jsonl','judge_raw_attempts.jsonl','judge_quality_detailed.jsonl','logical_accuracy_detailed.jsonl','bge_relevance_detailed.jsonl']]
 (W/'checkpoint_recovery_report.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False))
