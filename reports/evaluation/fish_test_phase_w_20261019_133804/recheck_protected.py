from __future__ import annotations
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
V=ROOT/"reports/evaluation/fish_test_phase_v_20261018_224918"
W=Path(__file__).resolve().parent
source=V/"frozen_baseline_recheck_phase_v_final.jsonl"
output=W/(sys.argv[1] if len(sys.argv)>1 else "protected_baseline_recheck.jsonl")
rows=[json.loads(x) for x in source.read_text(encoding="utf-8").splitlines() if x.strip()]
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""): h.update(block)
    return h.hexdigest()
out=[]; started=time.time()
for i,r in enumerate(rows,1):
    path=ROOT/r["path"]
    if not path.is_file():
        out.append({"path":r["path"],"expected_sha256":r["expected_sha256"],"actual_sha256":None,"size_bytes":None,"mtime_ns":None,"status":"MISSING"})
    else:
        actual=digest(path); st=path.stat()
        out.append({"path":r["path"],"expected_sha256":r["expected_sha256"],"actual_sha256":actual,"size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns,"status":"MATCH" if actual==r["expected_sha256"] else "MISMATCH"})
    if i%100==0: print(f"baseline {i}/{len(rows)}",flush=True)
output.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in out),encoding="utf-8")
sqlite=ROOT/"rag_store.sqlite3"; sqlsha=digest(sqlite) if sqlite.is_file() else None
summary={"records":len(out),"match":sum(x["status"]=="MATCH" for x in out),"mismatch":sum(x["status"]=="MISMATCH" for x in out),"missing":sum(x["status"]=="MISSING" for x in out),"production_sqlite_sha256":sqlsha,"production_sqlite_expected":"d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087","production_sqlite_match":sqlsha=="d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087","duration_seconds":time.time()-started,"output":str(output)}
(W/f"protected_baseline_recheck_summary_{output.stem}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(summary,ensure_ascii=True,indent=2))
