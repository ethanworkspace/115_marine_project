"""Sequential post-generation work; no Judge while Generator is resident."""
import json,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import evaluate_unified_rag_v6 as ev

def main():
    w=ev.work();started=time.monotonic()
    while True:
        p=w/'checkpoint.json';state=ev.read(p) if p.exists() else {'completed':0}
        if state.get('completed')==720:break
        if p.exists() and time.time()-p.stat().st_mtime>1800:raise RuntimeError('Generator checkpoint inactive for 30 minutes; do not falsely complete')
        if time.monotonic()-started>12*3600:raise RuntimeError('Evaluation preparation monitoring deadline reached')
        time.sleep(15)
    # The generator writes the last checkpoint just before its final unload
    # and manifest verification. Wait for that explicit completion event.
    while '"stage": "all_720_complete"' not in (w/'logs/generator_run.log').read_text(encoding='utf-8'):
        if time.monotonic()-started>12*3600:raise RuntimeError('No verified generator completion event')
        time.sleep(5)
    stages=[('scoring',[sys.executable,'-B',str(ROOT/'tools/score_unified_rag_v6.py')]),('summary',[sys.executable,'-B',str(ROOT/'tools/summarize_unified_rag_v6.py')]),('workbook',[r'C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt\dependencies\node\bin\node.exe',str(w/'build_evaluation_workbook.mjs')]),('workbook_validation',[sys.executable,'-B',str(ROOT/'tools/validate_v6_evaluation_workbook.py')])]
    for name,cmd in stages:
        ev.dump(w/'finalization_status.json',{'stage':name,'status':'RUNNING','at':ev.now()});ev.emit({'stage':name,'status':'STARTED'})
        with (w/'logs'/('finalize_'+name+'.log')).open('w',encoding='utf-8') as log:result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=os.environ,creationflags=0x08000000)
        ev.dump(w/'finalization_status.json',{'stage':name,'status':'COMPLETE' if result.returncode==0 else 'FAILED','returncode':result.returncode,'at':ev.now()})
        if result.returncode:raise RuntimeError(name+' failed; inspect saved full log')
    ev.dump(w/'finalization_status.json',{'stage':'ALL_COMPLETE','status':'COMPLETE','at':ev.now()});ev.emit({'stage':'ALL_COMPLETE'})

if __name__=='__main__':main()
