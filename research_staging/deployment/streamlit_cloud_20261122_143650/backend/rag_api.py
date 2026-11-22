"""Authenticated, loopback-only API for the existing single research RAG."""
from __future__ import annotations
import argparse, hashlib, hmac, json, logging, mimetypes, re, sqlite3, sys, threading, time, uuid
import platform
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[2]
APP = ROOT/'research_staging/app_sessions/launch_20261118_154253'
sys.dont_write_bytecode = True
sys.path[:0] = [str(WORK/'backend/vendor'),str(WORK/'backend'),str(APP),str(ROOT)]
from knowledge_notes import KnowledgeNotes
from website_answer_guard import protect_website_answer

class Service:
    def __init__(self, state=None):
        self.state = Path(state or WORK/'state')
        self.state.mkdir(parents=True,exist_ok=True)
        self.credentials = json.loads((WORK/'.private/credentials.json').read_text(encoding='utf-8'))
        registry=json.loads((WORK/'backend/model_registry.json').read_text(encoding='utf-8'))
        self.model_settings=registry['models']
        if set(self.model_settings)!={'M1','M2','M3','M4'}:raise RuntimeError('Invalid website model registry.')
        import PIL
        self.security_runtime={'pillow_version':PIL.__version__,'python_version':platform.python_version()}
        if int(PIL.__version__.split('.')[0])<13:raise RuntimeError('The isolated API requires patched Pillow 13 or newer.')
        self.active = json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8-sig'))
        self.runtime = None
        self.lock = threading.Lock()
        self.jobs_lock = threading.Lock()
        self.auth_lock = threading.Lock()
        self.auth_failures = deque(maxlen=21)
        self.notes = KnowledgeNotes(self.state/'knowledge_notes.sqlite3')
        with self.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, payload_digest TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
            con.execute('CREATE TABLE IF NOT EXISTS jobs (request_id TEXT PRIMARY KEY,payload_digest TEXT NOT NULL,status TEXT NOT NULL,response_json TEXT,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
            con.execute("UPDATE jobs SET status='FAILED',error='本機服務曾重新啟動，請重新送出問題。' WHERE status='RUNNING'")
            con.execute('CREATE TABLE IF NOT EXISTS published_media (asset_id TEXT PRIMARY KEY)')
            con.execute("""INSERT OR IGNORE INTO published_media SELECT DISTINCT json_extract(m.value,'$.remote_asset_id')
                FROM requests r,json_each(r.response_json,'$.question_payload.top5') c,json_each(c.value,'$.media_assets') m
                WHERE json_type(m.value,'$.remote_asset_id')='text'""")
        frozen = ROOT/'reports/evaluation/fish_test_final_fixed_denominator_run_20261023_010143/shared_contexts_180.jsonl'
        rows = [json.loads(line) for line in frozen.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.questions = {r['question_id']:{k:r.get(k) for k in ('question_id','question','species','category')} for r in rows}
        assert len(self.questions)==180
        registry = json.loads((Path(self.active['workspace'])/'source_registry.json').read_text(encoding='utf-8-sig'))
        entries = registry.values() if isinstance(registry,dict) else registry
        self.sources = {r['source_id']:{k:r.get(k) for k in ('source_id','title','publisher','attribution')} for r in entries}

    def db(self):
        con = sqlite3.connect(self.state/'cloud_requests.sqlite3',timeout=20)
        con.row_factory = sqlite3.Row
        return con

    def get_runtime(self):
        if self.runtime is None:
            import answer_policy, free_question_engine, unified_question_engine
            runtime_dir = self.state/'runtime'
            runtime_dir.mkdir(exist_ok=True)
            for name in ('prompts','streams','free_queries'):(runtime_dir/name).mkdir(exist_ok=True)
            for module in (answer_policy,free_question_engine,unified_question_engine): module.SESSION=runtime_dir
            self.runtime = unified_question_engine.UnifiedQuestionRag()
        return self.runtime

    def public_record(self, record):
        payload = record['question_payload']
        result = record['result']
        cited = set(result.get('supporting_chunk_ids',[]))
        contexts=[]
        for chunk in payload.get('top5',[]):
            if chunk['chunk_id'] not in cited: continue
            public = {k:chunk.get(k) for k in ('chunk_id','source_id','source_version','source_record_id','exact_locator','source_quote')}
            public['media_assets']=[{'remote_asset_id':a['asset_id'],'page':a.get('page'),'kind':a.get('kind')} for a in chunk.get('media_assets',[]) if a.get('asset_id')]
            contexts.append(public)
        flags = result.get('validation_status',{})
        safe_flags={k:flags.get(k) for k in ('raw_json_valid','raw_citation_valid','raw_span_binding_valid','not_human_gold','semantic_answer_completeness_independently_verified')}
        safe_flags['exact_quote_checks']=[{k:check.get(k) for k in ('chunk_id','quote','supported_answer_element','start_char','end_char','source_id','source_version','source_sha256','exact_locator','quote_verified')} for check in flags.get('exact_quote_checks',[])]
        return {k:record.get(k) for k in ('attempt_id','question_id','question','model_id','model_digest','context_digest','prompt_version','at','api_completed')} | {
            'api_error':bool(record.get('api_error')),
            'question_payload':{k:payload.get(k) for k in ('question_id','question','species','category','free_question')} | {'top5':contexts},
            'result':{k:result.get(k) for k in ('answer_status','answer_origin','raw_model_answer','final_answer','supporting_chunk_ids','missing_information')} | {
                'validation_status':safe_flags}}

    def protect_public(self, record):
        return protect_website_answer(record)

    def validate_question(self, body):
        allowed={'question','question_id','selected_species','model_id','request_id'}
        if set(body)-allowed: raise ValueError('不接受外部傳入的Context、Prompt或來源。')
        if not isinstance(body.get('model_id','M2'),str) or body.get('model_id','M2') not in self.model_settings:
            raise ValueError('請選擇網站提供的四款模型。')
        request_id=body.get('request_id','')
        if not isinstance(request_id,str):raise ValueError('請求識別碼無效。')
        try: uuid.UUID(request_id)
        except ValueError: raise ValueError('請求識別碼無效。')
        if body.get('question_id'):
            if not isinstance(body['question_id'],str) or 'question' in body:raise ValueError('問題欄位無效。')
            if body['question_id'] not in self.questions: raise ValueError('找不到指定題目。')
        else:
            if not isinstance(body.get('question'),str) or not body['question'].strip() or len(body['question'])>2000 or '\x00' in body['question']:
                raise ValueError('請輸入2,000字以內的問題。')
            if body.get('selected_species','全部魚種') not in ['全部魚種','虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']:
                raise ValueError('魚種選項無效。')

    def start_job(self, body):
        self.validate_question(body)
        request_id=body['request_id']
        digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.jobs_lock:
            with self.db() as con:
                completed=con.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
                if completed:
                    if completed['payload_digest']!=digest: raise ValueError('請求識別碼與內容不一致。')
                    return {'status':'DONE','request_id':request_id,'record':self.protect_public(json.loads(completed['response_json']))}
                old=con.execute('SELECT * FROM jobs WHERE request_id=?',(request_id,)).fetchone()
                if old:
                    if old['payload_digest']!=digest: raise ValueError('請求識別碼與內容不一致。')
                    return self.job(request_id)
                if self.lock.locked() or con.execute("SELECT count(*) FROM jobs WHERE status='RUNNING'").fetchone()[0]:
                    raise BlockingIOError('目前有問答進行中，請稍後再試。')
                con.execute("INSERT INTO jobs (request_id,payload_digest,status) VALUES (?,?,'RUNNING')",(request_id,digest))
            threading.Thread(target=self._job_worker,args=(body,),daemon=True).start()
        return {'status':'RUNNING','request_id':request_id}

    def _job_worker(self, body):
        request_id=body['request_id']
        try:
            record=self.ask(body)
            with self.db() as con: con.execute("UPDATE jobs SET status='DONE',response_json=? WHERE request_id=?",(json.dumps(record,ensure_ascii=False),request_id))
        except Exception:
            logging.exception('Background question failed; no authorization headers logged')
            with self.db() as con: con.execute("UPDATE jobs SET status='FAILED',error=? WHERE request_id=?",('本次問答未完成，請稍後再試。',request_id))

    def job(self, request_id):
        try: uuid.UUID(request_id)
        except ValueError:return None
        with self.db() as con: row=con.execute('SELECT * FROM jobs WHERE request_id=?',(request_id,)).fetchone()
        if not row:
            with self.db() as con: completed=con.execute('SELECT response_json FROM requests WHERE request_id=?',(request_id,)).fetchone()
            return {'status':'DONE','request_id':request_id,'record':self.protect_public(json.loads(completed[0]))} if completed else None
        result={'status':row['status'],'request_id':request_id}
        if row['status']=='DONE':result['record']=self.protect_public(json.loads(row['response_json']))
        if row['status']=='FAILED':result['error']=row['error']
        return result

    def ask(self, body):
        self.validate_question(body)
        request_id=body['request_id']
        payload_digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.db() as con: old=con.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['payload_digest']!=payload_digest: raise ValueError('請求識別碼與內容不一致。')
            return self.protect_public(json.loads(old['response_json']))
        if not self.lock.acquire(blocking=False): raise BlockingIOError('目前有問答進行中，請稍後再試。')
        try:
            with self.db() as con: old=con.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload_digest']!=payload_digest: raise ValueError('請求識別碼與內容不一致。')
                return self.protect_public(json.loads(old['response_json']))
            runtime=self.get_runtime()
            model=body.get('model_id','M2')
            identity=runtime.runtime.model_identity(model)
            if identity.get('digest')!=self.model_settings[model]['digest']:raise RuntimeError('Selected model digest differs from the verified registry.')
            if body.get('question_id'):
                question=self.questions.get(body['question_id'])
                if question is None: raise ValueError('找不到指定題目。')
                record=runtime.call(question,model,stage='STREAMLIT_CLOUD_QUESTION')
            else:
                question=str(body.get('question','')).strip()
                species=body.get('selected_species','全部魚種')
                if not question or len(question)>2000: raise ValueError('請輸入2,000字以內的問題。')
                if species not in ['全部魚種','虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']: raise ValueError('魚種選項無效。')
                record=runtime.call_free(question,model,selected_species=species)
            if record.get('model_id')!=model or record.get('model_digest')!=self.model_settings[model]['digest']:
                raise RuntimeError('Generator response model identity mismatch.')
            public=self.protect_public(self.public_record(record))
            with self.db() as con:
                con.execute('INSERT INTO requests (request_id,payload_digest,response_json) VALUES (?,?,?)',(request_id,payload_digest,json.dumps(public,ensure_ascii=False)))
                for context in public['question_payload']['top5']:
                    for asset in context.get('media_assets',[]):
                        con.execute('INSERT OR IGNORE INTO published_media VALUES (?)',(asset['remote_asset_id'],))
            return public
        finally: self.lock.release()

    def media(self, asset_id):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',asset_id): return None
        with self.db() as con:
            if not con.execute('SELECT 1 FROM published_media WHERE asset_id=?',(asset_id,)).fetchone():return None
        with sqlite3.connect(Path(self.active['database']).as_uri()+'?mode=ro',uri=True) as con:
            row=con.execute('SELECT path FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
        if not row: return None
        try:path=Path(row[0]).resolve(strict=True)
        except (OSError,RuntimeError):return None
        if not path.is_relative_to(ROOT.resolve()):return None
        mime=mimetypes.guess_type(path.name)[0]
        if not path.is_file() or mime not in ('image/png','image/jpeg','image/webp') or path.stat().st_size>8*1024*1024: return None
        return mime,path.read_bytes()

class Handler(BaseHTTPRequestHandler):
    server_version='MarineKnowledgeAPI/1'
    sys_version=''
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self, fmt, *args):
        logging.info('%s %s',self.client_address[0],fmt%args)

    def send_json(self, status, value):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        supplied=self.headers.get('Authorization','')
        expected='Bearer '+self.server.service.credentials['api_key']
        return hmac.compare_digest(supplied.encode('utf-8'),expected.encode('utf-8'))

    def check_authorization(self):
        if self.authorized():return True
        service=self.server.service
        with service.auth_lock:
            now=time.monotonic()
            while service.auth_failures and now-service.auth_failures[0]>60:service.auth_failures.popleft()
            service.auth_failures.append(now)
            status=429 if len(service.auth_failures)>20 else 401
        self.send_json(status,{'error':'未授權的連線。' if status==401 else '連線嘗試過於頻繁，請稍後再試。'})
        return False

    def do_GET(self):
        parts=urlsplit(self.path)
        if parts.path=='/health': return self.send_json(200,{'status':'ok','service':'marine-knowledge-api'})
        if not self.check_authorization():return
        if self.headers.get('Origin'):return self.send_json(403,{'error':'本服務僅接受已授權的伺服器連線。'})
        service=self.server.service
        if parts.path=='/v1/bootstrap':
            return self.send_json(200,{'questions':service.questions,'sources':service.sources,'corpus_version':service.active['version'],
                'model_ids':list(service.model_settings),'default_model_id':'M2','models':service.model_settings,'security_runtime':service.security_runtime})
        if parts.path.startswith('/v1/jobs/'):
            job=service.job(parts.path[len('/v1/jobs/'):])
            return self.send_json(200,job) if job else self.send_json(404,{'error':'找不到這個問答請求。'})
        if parts.path=='/v1/history':
            with service.db() as con: rows=con.execute('SELECT response_json FROM requests ORDER BY created_at DESC,rowid DESC LIMIT 50').fetchall()
            return self.send_json(200,{'records':list(reversed([service.protect_public(json.loads(r[0])) for r in rows]))})
        if parts.path=='/v1/notes':
            query=parse_qs(parts.query)
            return self.send_json(200,{'notes':service.notes.list(query.get('query',[''])[0][:200],query.get('species',['全部魚種'])[0],query.get('topic',['全部主題'])[0])})
        if parts.path.startswith('/v1/media/'):
            asset=service.media(parts.path[len('/v1/media/'):])
            if not asset: return self.send_json(404,{'error':'找不到可顯示的圖像。'})
            mime,data=asset
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','private, max-age=300');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            return
        return self.send_json(404,{'error':'找不到這個服務。'})

    def do_POST(self):
        if not self.check_authorization():return
        try:
            if self.headers.get('Origin'):return self.send_json(403,{'error':'本服務僅接受已授權的伺服器連線。'})
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                return self.send_json(400,{'error':'請求長度格式無效。'})
            if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                return self.send_json(415,{'error':'請以JSON格式送出資料。'})
            length=int(self.headers.get('Content-Length','0'))
            if length<2 or length>131072: return self.send_json(413,{'error':'資料大小不符限制。'})
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('JSON必須是物件。')
            route=urlsplit(self.path).path
            if route=='/v1/jobs':
                job=self.server.service.start_job(body)
                return self.send_json(200 if job['status']=='DONE' else 202,job)
            if route=='/v1/ask': return self.send_json(200,{'record':self.server.service.ask(body)})
            if route=='/v1/notes':
                allowed={'title','body','species','topic','note_id','origin','provenance'}
                if set(body)-allowed: raise ValueError('小知識欄位無效。')
                if not isinstance(body.get('title'),str) or not isinstance(body.get('body'),str):raise ValueError('小知識內容必須是文字。')
                if body.get('note_id') is not None and (not isinstance(body['note_id'],str) or not re.fullmatch('[a-f0-9]{32}',body['note_id'])):raise ValueError('小知識識別碼無效。')
                if body.get('origin','PERSONAL_NOTE') not in ('PERSONAL_NOTE','SAVED_RAG_ANSWER'):raise ValueError('小知識來源類型無效。')
                provenance=body.get('provenance',{})
                if not isinstance(provenance,dict) or len(json.dumps(provenance))>16000:raise ValueError('小知識來源資料過長。')
                note_id=self.server.service.notes.save(**body)
                return self.send_json(200,{'note_id':note_id})
            return self.send_json(404,{'error':'找不到這個服務。'})
        except BlockingIOError as exc: return self.send_json(429,{'error':str(exc)})
        except (ValueError,TypeError,KeyError): return self.send_json(400,{'error':'請確認問題或小知識內容與必填欄位。'})
        except Exception:
            logging.exception('Request failed without logging authorization headers or request body')
            return self.send_json(503,{'error':'本機問答服務暫時無法完成，請稍後再試。'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, address, service):
        self.service=service
        self.connection_slots=threading.BoundedSemaphore(16)
        super().__init__(address,Handler)

    def process_request(self, request, address):
        if not self.connection_slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:
            self.connection_slots.release();raise

    def process_request_thread(self, request, address):
        try:super().process_request_thread(request,address)
        finally:self.connection_slots.release()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    service=Service()
    logging.info('Starting authenticated loopback API on 127.0.0.1:%s; model loads on demand',args.port)
    Server(('127.0.0.1',args.port),service).serve_forever()
