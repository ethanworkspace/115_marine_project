"""Full edge RAG execution revision two. No production, policy or artifact writes."""
from __future__ import annotations
import datetime as dt
import gc
import json
import math
import os
import subprocess
import sys
import threading
import queue
import time
import traceback
from array import array
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from src.evaluation.generation.frozen import read_jsonl,validate_frozen_inputs
from src.evaluation.edge.inputs import load_bundle,load_target,BUNDLE
from src.evaluation.edge.core import OPTIONS,behavior_preservation
from src.evaluation.edge.core19b import schedule,utc_now,compare_top5,frozen_context_check
from src.evaluation.edge.exec19b_r2 import valid_block,restart_plan,residency_changes
from src.evaluation.edge.runtime import OllamaEdge
from src.evaluation.edge.runner import execute_protocol,append_jsonl
from src.evaluation.edge.execution19a import LowLatencySession
from src.evaluation.edge.hardware19a import Sensors
from src.evaluation.edge.telemetry19b import windows_process_tree
from src.evaluation.edge.recovery19b1 import parse_event
OUT=ROOT/'reports/evaluation/edge/phase19B_exec_r2'
RERANKER_PYTHON=ROOT/'.venv-reranker/Scripts/python.exe'


def write(name,obj):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


class DefaultResidencySession(LowLatencySession):
    def post(self,*args,**kw):
        # Same schema/model/options invocation, with the common server residency default.
        if isinstance(kw.get('json'),dict):
            kw['json']=dict(kw['json']);kw['json'].pop('keep_alive',None)
        return super().post(*args,**kw)


class Collector:
    def __init__(self):
        self.sensor=Sensors();self.latest=None;self.records=[];self.errors=[]
        self.stop=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.stop.is_set():
            try:
                r=self.sensor.sample();r['process_tree']=windows_process_tree(os.getpid(),os.getpid())
                self.latest=r;self.records.append(r);append_jsonl(OUT/'sensor_samples.jsonl',r)
            except Exception as exc:self.errors.append(str(exc))
            self.stop.wait(2)
    def start(self):self.thread.start()
    def finish(self):
        self.stop.set();self.thread.join(timeout=15);self.sensor.close()
        write('telemetry_limitations.json',dict(errors=self.errors+list(self.sensor.errors),
            PDH_errors=self.sensor.pdh.errors if self.sensor.pdh else ['PDH unavailable'],
            sampled_peak_not_absolute_peak=True,interval_seconds=2))


class CodeIntegrityMonitor:
    def __init__(self):self.cursor=utc_now();self.seen=set();self.captures=[]
    def capture(self,point):
        end=utc_now();start=self.cursor
        code=r'''[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$start='START';$end='END';$log='Microsoft-Windows-CodeIntegrity/Operational'
$xml="<QueryList><Query Id='0' Path='$log'><Select Path='$log'>*[System[TimeCreated[@SystemTime&gt;='$start' and @SystemTime&lt;='$end']]]</Select></Query></QueryList>"
try {$ev=@(Get-WinEvent -FilterXml $xml -MaxEvents 2000 -ErrorAction Stop);$rows=@($ev|ForEach-Object {$raw=$_.ToXml();$x=[xml]$raw;@{event_id=$_.Id;record_id=$_.RecordId;timestamp=$x.Event.System.TimeCreated.SystemTime;provider=$_.ProviderName;message=$_.Message;raw_event_xml=$raw}});@{status='collected';events=$rows;capped=($ev.Count -eq 2000)}|ConvertTo-Json -Depth 12 -Compress}
catch {@{status=$(if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {'no_events'} else {'unavailable'});events=@();error=$_.Exception.Message;error_id=$_.FullyQualifiedErrorId}|ConvertTo-Json -Depth 6 -Compress}'''
        code=code.replace('START',start).replace('END',end)
        proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],capture_output=True,
            encoding='utf-8',errors='replace',timeout=45)
        try:data=json.loads(proc.stdout)
        except Exception:data=dict(status='unavailable',error=proc.stderr,raw_stdout=proc.stdout,events=[])
        events=[]
        for r in data.get('events') or []:
            if r['record_id'] in self.seen:continue
            self.seen.add(r['record_id']);events.append(parse_event(r))
        relevant=[r for r in events if r['event_id'] in (3077,3033) and any(s in
            (str(r.get('blocked_path'))+' '+str(r.get('event_data'))).casefold() for s in
            ('.venv-reranker','torch\\lib','python314','bge-reranker'))]
        record=dict(point=point,start_utc=start,end_utc=end,count=len(events),
            relevant_execution_block_count=len(relevant),status=data['status'],events=events,
            error=data.get('error'),capped=data.get('capped',False),read_only=True)
        append_jsonl(OUT/'code_integrity_monitor.jsonl',record);self.captures.append(record);self.cursor=end
        return record


class RerankerProxy:
    def __init__(self,name):
        self.log=(OUT/(name+'.worker.stderr.log')).open('x',encoding='utf-8')
        self.process=subprocess.Popen([str(RERANKER_PYTHON),'-B',str(ROOT/'scripts/phase19b_r2_reranker_worker.py')],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'},
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.queue=queue.Queue()
        def read():
            for line in self.process.stdout:self.queue.put(line)
            self.queue.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.info=self.receive()
        if not self.info.get('ready'):raise RuntimeError('Reranker worker load failed: '+str(self.info))
    def receive(self):
        try:line=self.queue.get(timeout=900)
        except queue.Empty:raise RuntimeError('Reranker runtime timeout')
        if line is None:raise RuntimeError('Reranker process exited')
        return json.loads(line)
    def call(self,request):
        self.process.stdin.write(json.dumps(request,ensure_ascii=True)+'\n');self.process.stdin.flush()
        reply=self.receive()
        if not reply.get('ok'):raise RuntimeError('Reranker runtime failure: '+str(reply))
        return reply['value']
    def score_pairs(self,query,texts):return self.call(dict(operation='score',query=query,texts=texts))
    def rerank(self,query,candidates):return self.call(dict(operation='rerank',query=query,candidates=candidates))
    def close(self):
        try:
            self.process.stdin.write(json.dumps({'operation':'close'})+'\n');self.process.stdin.flush()
            self.process.wait(timeout=30)
        except Exception:
            self.process.terminate();self.process.wait(timeout=15)
        self.log.close()


class Pipeline:
    def __init__(self,frozen,rows):
        from src.evaluation.grounded_baselines import load_dense_index,OllamaEmbeddingRuntime
        from src.evaluation.retrievers.bm25 import EvaluationBM25
        from src.evaluation.silver import _eligible_corpus
        self.frozen=frozen;self.rows=rows;self.corpus=_eligible_corpus(frozen['corpus'])
        if len(self.corpus)!=2224:raise RuntimeError('Frozen retrieval corpus count differs')
        self.bm=EvaluationBM25(self.corpus,corpus_sha256=frozen['hashes']['evaluation_corpus_v2_sha256'])
        self.dense,self.index=load_dense_index(ROOT,{'corpus':self.corpus,'questions':frozen['questions'],
            'hashes':{'evaluation_corpus_v2':frozen['hashes']['evaluation_corpus_v2_sha256']}})
        self.embed=OllamaEmbeddingRuntime();self.embed.dimension=1024
        self.reranker=None
    def preflight(self,name):
        result=dict(timestamp=utc_now(),torch_import=False,CUDA=False,model_load=False,single_pair=False,
                    device='cuda:0',CPU_fallback=False,model_revision='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e')
        code="import torch,json;print(json.dumps({'torch':torch.__version__,'CUDA_build':torch.version.cuda,'CUDA':torch.cuda.is_available(),'GPU':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))"
        p=subprocess.run([str(RERANKER_PYTHON),'-B','-c',code],capture_output=True,encoding='utf-8',errors='replace',timeout=120,
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
        result.update(loader_probe_exit=p.returncode,loader_stdout=p.stdout,loader_stderr=p.stderr)
        try:
            if p.returncode:raise RuntimeError('Fresh torch loader probe failed: '+p.stderr)
            probe=json.loads(p.stdout);result.update(probe);result['torch_import']=True
            if probe['torch']!='2.14.1+cu130' or not probe['CUDA'] or probe['GPU']!='NVIDIA GeForce RTX 4060':
                raise RuntimeError('Pinned torch/CUDA/GPU gate failed')
            self.reranker=RerankerProxy(name)
            result['model_load']=True;result['worker']=self.reranker.info
            result['model_load_seconds']=self.reranker.info['model_load_seconds']
            qs=read_jsonl(ROOT/'reports/evaluation/reranker_runtime/e3_rrf_top50_candidates.jsonl')
            q=self.rows[0]['question'];cs=sorted([c for c in qs if c['question_id']==q['question_id']],key=lambda c:c['rank'])[:2]
            scores=self.reranker.score_pairs(q['question'],[c['text'] for c in cs])
            result.update(scores=scores,candidate_ids=[c['chunk_id'] for c in cs],single_pair=len(scores)==2 and all(math.isfinite(s) for s in scores))
            result['passed']=result['single_pair']
        except Exception as exc:result.update(passed=False,error=str(exc),traceback=traceback.format_exc())
        write(name,result);return result
    def retrieve(self,item,checkpoint=lambda *a:None):
        from src.evaluation.rrf import fuse_ranked_lists
        q=item['question'];query=q['question'];m={}
        def stage(name,fn):
            a=time.perf_counter();v=fn();m[name]=(time.perf_counter()-a)*1000;return v
        bm=stage('bm25_ms',lambda:self.bm.retrieve(query,top_k=50))
        vec=stage('dense_embedding_ms',lambda:array('f',self.embed.embed_texts([query],batch_size=32)[0]).tolist())
        dense=stage('dense_search_ms',lambda:self.dense.rank_vector(vec)[:50]);checkpoint('after_dense')
        fused=stage('rrf_ms',lambda:fuse_ranked_lists(bm,dense,self.frozen['corpus_by_id'],k=60,top_n=50))
        candidates=[dict(chunk_id=r['chunk_id'],document_id=r['document_id'],page=r['page'],
            rank=r['final_rank'],rrf_rank=r['final_rank'],rrf_score=r['rrf_score'],bm25_rank=r['bm25_rank'],dense_rank=r['dense_rank'],
            text=self.frozen['corpus_by_id'][r['chunk_id']]['text']) for r in fused]
        ranked=stage('reranker_ms',lambda:self.reranker.rerank(query,candidates));checkpoint('after_reranker')
        contexts=stage('context_assembly_ms',lambda:[dict(context_id='C'+str(i),chunk_id=c['chunk_id'],document_id=c['document_id'],
            page=c['page'],rank=i,text=c['text']) for i,c in enumerate(ranked[:5],1)])
        m['retrieval_to_context_ms']=sum(m.values())
        integrity=frozen_context_check(item['contexts'],contexts)
        return contexts,m,integrity,ranked


def execute():
    if (OUT/'execution_start.json').exists():raise SystemExit('Existing execution journal; no automatic splice/restart of experiment')
    manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'));rows,bundle=load_bundle();frozen=validate_frozen_inputs(ROOT)
    if manifest['question_ids']!=bundle['question_ids']:raise ValueError('Frozen question order changed')
    target=load_target();adapter=OllamaEdge(target,session=DefaultResidencySession())
    adapter.preflight(manifest['models']);monitor=CodeIntegrityMonitor();collector=Collector();collector.start()
    prompt=(BUNDLE/'generation_v2.txt').read_text(encoding='utf-8').strip();schema=json.loads((BUNDLE/'generation_output_v2.schema.json').read_text())
    references={(r['model'],r['question_id']):r for r in read_jsonl(BUNDLE/'phase17_behavior_references.jsonl')}
    old19a={}
    for r in read_jsonl(ROOT/'reports/evaluation/edge/phase19A/warm_runs.jsonl'):
        if r['repetition']==1:old19a[(r['model'],r['question_id'])]=r['result']
    pipeline=None;blocks=[];all_rows=[];seen=set();status='initializing';interruption=None
    write('execution_start.json',dict(timestamp=utc_now(),execution_id='phase19B_exec_r2',pid=os.getpid()))
    def check(node,identity):
        ps=adapter.allocations();sensor=collector.latest
        record=dict(**identity,node=node,timestamp=utc_now(),monotonic=time.perf_counter(),loaded_ollama_models=ps,
            telemetry=sensor,telemetry_age_seconds=time.monotonic()-sensor['timestamp'] if sensor else None,
            process_tree=windows_process_tree(os.getpid(),pipeline.reranker.process.pid if pipeline and pipeline.reranker else None))
        append_jsonl(OUT/'residency_trace.jsonl',record);return record
    def env_start(run_id):
        start=time.monotonic();reached=False
        while time.monotonic()-start<300:
            sample=collector.latest or {};g=sample.get('gpu') or {}
            if g.get('utilization_percent') is not None and g['utilization_percent']<5 and g.get('temperature_c') is not None and g['temperature_c']<=45:
                reached=True;break
            time.sleep(2)
        append_jsonl(OUT/'environment_baselines.jsonl',dict(run_id=run_id,timestamp=utc_now(),
            wait_seconds=time.monotonic()-start,environment_start_protocol_complete=reached,sample=collector.latest,
            loaded_models=adapter.allocations(),process_tree=windows_process_tree(os.getpid(),pipeline.reranker.process.pid if pipeline and pipeline.reranker else None)))
    def request(item,condition,rep,run_id,pos,stage='formal'):
        accepted=time.perf_counter();identity=dict(run_id=run_id,condition=condition,repetition=rep,
            question_id=item['question']['question_id'],question_position=pos,stage=stage)
        record=dict(**identity,timestamp=utc_now(),context_band=item['subset_row']['context_band'],
            retrieval_failed=False,generation_failed=False,final_failed=False,runtime_failure=False,
            OOM=False,runtime_crash=False,retrieval_drift=False)
        checkpoint_rows=[]
        def cp(node):
            value=check(node,identity);checkpoint_rows.append(value);return value
        try:
            cp('request_start');contexts,m,match,ranked=pipeline.retrieve(item,cp)
            record.update(m,retrieval_drift=not match,retrieved_chunk_ids=[c['chunk_id'] for c in contexts],
                contexts_sha256=item['subset_row']['context_sha256'] if match else None)
            append_jsonl(OUT/'retrieval_results.jsonl',dict(**identity,top5=contexts,
                RRF_and_reranker=[{k:r.get(k) for k in ('chunk_id','rrf_rank','rrf_score','reranker_rank','reranker_score')} for r in ranked],match=match))
            if not match:record.update(retrieval_failed=True,final_failed=True)
            cp('before_generator')
            if condition!='R0_edge_retrieval_only':
                model='gemma2:9b' if condition=='F1_edge_fullrag_gemma' else 'qwen2.5-coder:7b'
                captures=[]
                def call(**kwargs):
                    value=adapter.generation(**kwargs);captures.append(value);return value
                result=execute_protocol(item['question'],contexts,manifest['models'][model],adapter,OUT,
                    run_id,rep,prompt,schema,call_hook=call)
                record['generation']=result;record['model']=model
                record.update(generation_failed=not result['final_schema_valid'] or result['status']=='generation_error',
                    generator_load_reload_ms=(result['runtime_load_duration_ns']/1e6 if result.get('runtime_load_duration_ns') is not None else None),
                    generator_ttft_any_ms=result['ttft_any_token_seconds']*1000 if result.get('ttft_any_token_seconds') is not None else None,
                    generator_ttft_final_ms=result['retry_inclusive_ttft_final_answer_seconds']*1000 if result.get('retry_inclusive_ttft_final_answer_seconds') is not None else None,
                    generation_completion_ms=result['retry_inclusive_latency_seconds']*1000,
                    e2e_ttft_final_ms=(time.perf_counter()-accepted-result['retry_inclusive_latency_seconds']+result['retry_inclusive_ttft_final_answer_seconds'])*1000 if result.get('retry_inclusive_ttft_final_answer_seconds') is not None else None,
                    behavior_phase17=behavior_preservation(references[(model,identity['question_id'])],result['result']),
                    behavior_phase19A=behavior_preservation(old19a[(model,identity['question_id'])],result['result']),
                    first_pass_JSON_valid=captures[0]['parsed'] is not None and captures[0]['parse_error'] is None,
                    final_JSON_valid=captures[-1]['parsed'] is not None and captures[-1]['parse_error'] is None,
                    prompt_evaluation_ms=captures[-1]['final_event'].get('prompt_eval_duration',0)/1e6,
                    generator_eval_ms=captures[-1]['final_event'].get('eval_duration',0)/1e6)
                categories={f['category'] for f in result.get('technical_failures',[])}
                record['OOM']='OOM' in categories;record['runtime_crash']='runtime_crash_or_unavailable' in categories
                record['context_capacity_failure']='context_capacity_failure' in categories
                record['final_failed']=record['final_failed'] or record['generation_failed']
            cp('after_generator')
        except Exception as exc:
            record.update(final_failed=True,retrieval_failed=True,runtime_failure=True,error=str(exc),traceback=traceback.format_exc())
            low=str(exc).casefold();record['OOM']='out of memory' in low or 'cuda oom' in low
            record['runtime_crash']=True
        record['e2e_total_latency_ms']=(time.perf_counter()-accepted)*1000
        record['telemetry_start_monotonic']=accepted;record['telemetry_end_monotonic']=time.perf_counter()
        observations=[r['loaded_ollama_models'] for r in checkpoint_rows]
        changes=[]
        for a,b in zip(observations,observations[1:]):
            changes.append(residency_changes(a,b,seen,record.get('generator_load_reload_ms')))
            seen.update(m.get('name',m.get('model')) for m in b.get('models',[]))
        record['residency_events']=changes
        append_jsonl(OUT/'stage_metrics.jsonl',record);all_rows.append(record)
        print(json.dumps({'stage':stage,'run_id':run_id,'question':pos+1,'condition':condition,
            'e2e_ms':round(record['e2e_total_latency_ms']),'failed':record['final_failed'],'drift':record['retrieval_drift']},ensure_ascii=True),flush=True)
        return record
    try:
        monitor.capture('benchmark_start');pipeline=Pipeline(frozen,rows)
        gate=pipeline.preflight('fresh_preflight.json')
        if not gate['passed']:raise RuntimeError('Fresh runtime preflight failed; stop')
        reproduced=[]
        for i,item in enumerate(rows):
            contexts,m,match,_=pipeline.retrieve(item);reproduced.append(dict(question_id=item['question']['question_id'],match=match,metrics=m))
            print(json.dumps({'gate':'E4_reproduction','checked':i+1,'match':match}),flush=True)
            if not match:break
        passed=len(reproduced)==60 and all(r['match'] for r in reproduced)
        write('e4_reproduction.json',dict(passed=passed,checked=len(reproduced),matched=sum(r['match'] for r in reproduced),results=reproduced))
        if not passed:raise RuntimeError('Fresh E4 reproduction mismatch; stop without tuning')
        status='formal'
        for number,spec in enumerate(schedule(),1):
            for revision in (1,2):
                run_id=f"r{spec['repetition']}_{spec['condition']}_attempt{revision}"
                if revision==2:
                    if pipeline.reranker:pipeline.reranker.close()
                    pipeline.reranker=None;gc.collect()
                    gate=pipeline.preflight('restart_preflight_'+run_id+'.json')
                    append_jsonl(OUT/'block_restarts.jsonl',dict(run_id=run_id,**restart_plan(previous_id,gate['passed'])))
                    if not gate['passed']:raise RuntimeError('Restart preflight failed; stop execution')
                env_start(run_id);block_start=time.perf_counter();rs=[]
                for pos,item in enumerate(rows):
                    r=request(item,spec['condition'],spec['repetition'],run_id,pos);rs.append(r)
                    if r['runtime_failure']:break
                captured=monitor.capture('formal_block_end_'+run_id)
                runtime_valid=not any(r['runtime_failure'] for r in rs) and captured['relevant_execution_block_count']==0
                block=dict(**spec,run_id=run_id,completed=len(rs)==60,runtime_valid=runtime_valid,
                    relevant_policy_blocks=captured['relevant_execution_block_count'],event_capture_status=captured['status'],
                    question_ids=[r['question_id'] for r in rs],requests=len(rs),elapsed_seconds=time.perf_counter()-block_start)
                block['primary_metrics_valid']=valid_block(block,bundle['question_ids'])
                append_jsonl(OUT/'formal_blocks.jsonl',block);blocks.append(block)
                if block['primary_metrics_valid']:break
                previous_id=run_id
                if revision==2:raise RuntimeError('Formal block remains invalid after one fixed restart; diagnostics preserved')
        for condition,model in [('F1_edge_fullrag_gemma','gemma2:9b'),('F2_edge_fullrag_qwen','qwen2.5-coder:7b')]:
            bs=[b for b in blocks if b['condition']==condition and b['primary_metrics_valid']]
            rs=[r for r in all_rows if r['run_id'] in {b['run_id'] for b in bs}]
            if len(bs)!=3 or len(rs)!=180 or any(r['final_failed'] or r['OOM'] or r['runtime_crash'] for r in rs):
                write('sustained_'+('gemma' if 'gemma' in condition else 'qwen')+'_execution.json',dict(completed=False,gate_pass=False,reason='Three complete successful formal blocks required'))
                continue
            run_id='sustained_'+model.replace(':','_');env_start(run_id)
            start=time.monotonic();i=0;capture_at=300;runtime_valid=True
            while time.monotonic()-start<1800:
                r=request(rows[i%60],condition,0,run_id,i%60,stage='sustained')
                append_jsonl(OUT/'sustained_requests.jsonl',dict(**r,elapsed_start_seconds=r['telemetry_start_monotonic']-start,
                    interval_index=min(5,int((r['telemetry_start_monotonic']-start)//300))))
                i+=1
                if r['runtime_failure']:runtime_valid=False;break
                if time.monotonic()-start>=capture_at:
                    event=monitor.capture(run_id+'_interval_'+str(capture_at//300));capture_at+=300
                    if event['relevant_execution_block_count']:runtime_valid=False;break
            event=monitor.capture(run_id+'_end')
            write('sustained_'+('gemma' if 'gemma' in condition else 'qwen')+'_execution.json',dict(model=model,
                completed=time.monotonic()-start>=1800 and runtime_valid,gate_pass=True,configured_seconds=1800,
                elapsed_seconds=time.monotonic()-start,requests=i,runtime_valid=runtime_valid,
                final_relevant_policy_block_count=event['relevant_execution_block_count'],last_request_may_finish_after_30_minutes=True))
        status='complete'
    except Exception as exc:
        interruption=dict(error=str(exc),traceback=traceback.format_exc(),timestamp=utc_now(),status=status)
        write('execution_interruption.json',interruption);status='blocked_or_incomplete'
    finally:
        try:monitor.capture('benchmark_end')
        except Exception as exc:append_jsonl(OUT/'monitor_errors.jsonl',dict(error=str(exc),point='benchmark_end'))
        if pipeline and pipeline.reranker:pipeline.reranker.close()
        collector.finish()
        write('runtime_continuity.json',dict(status=status,blocks=blocks,
            valid_formal_blocks=sum(b['primary_metrics_valid'] for b in blocks),
            invalid_formal_blocks=sum(not b['primary_metrics_valid'] for b in blocks),
            partial_runs_primary_excluded=True,partial_runs_preserved=True,interruption=interruption,
            policy_allow_reason='unknown',permanent_security_fix_claimed=False))
        write('execution_complete.json',dict(status=status,timestamp=utc_now(),requests_executed=len(all_rows),
            valid_primary_requests=sum(b['requests'] for b in blocks if b['primary_metrics_valid'])))
        print(json.dumps({'execution_status':status,'formal_blocks':len(blocks),'requests_executed':len(all_rows)}),flush=True)

if __name__=='__main__':execute()
