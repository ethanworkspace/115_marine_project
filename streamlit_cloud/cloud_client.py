"""Portable Streamlit client; model weights, corpus and note storage stay local."""
from __future__ import annotations
import hashlib,hmac,json,os,time,uuid
from urllib.parse import urlsplit
import requests
import streamlit as st

TOPICS=['養殖管理','水質環境','魚種認識','氣候防寒','疾病觀察','其他']
SPECIES=['通用','虱目魚','吳郭魚','石斑魚','鱸魚','烏魚','鰻魚']

class BackendError(RuntimeError): pass

def setting(name):
    value=os.environ.get(name)
    if value is not None:return value
    try:return str(st.secrets.get(name,''))
    except (FileNotFoundError,st.errors.StreamlitSecretNotFoundError):return ''

@st.cache_data(ttl=30,show_spinner=False)
def discover_backend(discovery_url):
    parts=urlsplit(discovery_url)
    if parts.scheme!='https' or parts.hostname!='raw.githubusercontent.com' or parts.username or parts.password:
        raise BackendError('後端連線清單位置不正確。')
    try:
        response=requests.get(discovery_url,timeout=(10,20),allow_redirects=False)
        response.raise_for_status()
        endpoint=response.json()['backend_url']
    except (requests.RequestException,ValueError,KeyError):
        raise BackendError('本機知識服務尚未連線，請稍後再試。') from None
    address=urlsplit(endpoint)
    if address.scheme!='https' or not (address.hostname or '').endswith('.trycloudflare.com') or address.port not in (None,443):
        raise BackendError('後端連線清單中的安全網址不正確。')
    return endpoint

def gate():
    code=setting('APP_ACCESS_CODE')
    if not code:
        st.title('Aquaculture Knowledge Platform')
        st.info('網站已準備就緒，尚需設定研究工作區的存取碼與本機知識服務連線。')
        st.stop()
    stamp=hashlib.sha256(code.encode()).hexdigest()
    if hmac.compare_digest(str(st.session_state.get('_cloud_access_hash','')),stamp):
        st.session_state.pop('cloud_access_input',None)
        return
    st.title('Aquaculture Knowledge Platform')
    st.caption('輸入工作區存取碼，開始問答與記錄小知識。')
    with st.form('cloud_login'):
        supplied=st.text_input('工作區存取碼',type='password',key='cloud_access_input')
        if st.form_submit_button('進入知識平台',type='primary'):
            if hmac.compare_digest(supplied.encode(),code.encode()):
                st.session_state['_cloud_access_hash']=stamp
                st.rerun()
            else:st.error('存取碼不正確，請重新輸入。')
    st.stop()

class Client:
    def __init__(self):
        self.url=setting('RAG_BACKEND_URL').strip().rstrip('/')
        if not self.url and setting('RAG_BACKEND_DISCOVERY_URL'):
            self.url=discover_backend(setting('RAG_BACKEND_DISCOVERY_URL')).rstrip('/')
        self.key=setting('RAG_API_KEY').strip()
        parts=urlsplit(self.url)
        local=(parts.hostname in ('127.0.0.1','localhost') and setting('MARINE_ALLOW_LOOPBACK')=='1')
        if not self.key or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('','/'):
            raise BackendError('請先設定本機知識服務的安全連線。')
        if parts.scheme!='https' and not (local and parts.scheme=='http'):
            raise BackendError('知識服務必須使用HTTPS安全連線。')

    def request(self,method,path,**kwargs):
        try:
            response=requests.request(method,self.url+path,headers={'Authorization':'Bearer '+self.key},
                timeout=(10,600 if path=='/v1/ask' else 30),allow_redirects=False,**kwargs)
        except requests.RequestException:
            raise BackendError('暫時連不上本機知識服務，請確認服務電腦與安全連線已啟動。') from None
        if response.status_code==401:raise BackendError('知識服務金鑰尚未完成設定或已更新。')
        if response.status_code==429:raise BackendError('目前有問答正在進行，請稍後再試。')
        if response.status_code not in (200,202):raise BackendError('知識服務暫時無法完成請求，請稍後再試。')
        if not response.headers.get('Content-Type','').startswith('application/json'):
            raise BackendError('安全連線未回傳預期資料，請確認本機連線狀態。')
        try:return response.json()
        except ValueError:raise BackendError('知識服務回傳格式不完整，請稍後再試。') from None

    def bootstrap(self):
        body=self.request('GET','/v1/bootstrap')
        return body['questions'],body['sources']

    def call_free(self,text,model='M2',selected_species='全部魚種'):
        return self.ask({'question':text,'model_id':model,'selected_species':selected_species})

    def call(self,question,model='M2',stage=None):
        return self.ask({'question_id':question['question_id'],'model_id':model})

    def ask(self,body):
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        pending=st.session_state.get('_cloud_pending_question',{})
        request_id=pending.get('request_id') if pending.get('fingerprint')==fingerprint else str(uuid.uuid4())
        st.session_state['_cloud_pending_question']={'fingerprint':fingerprint,'request_id':request_id}
        body=body|{'request_id':request_id}
        response=self.request('POST','/v1/jobs',json=body)
        deadline=time.monotonic()+600
        while response['status']=='RUNNING' and time.monotonic()<deadline:
            time.sleep(1)
            response=self.request('GET','/v1/jobs/'+request_id)
        if response['status']=='DONE':
            st.session_state.pop('_cloud_pending_question',None)
            return response['record']
        if response['status']=='FAILED':st.session_state.pop('_cloud_pending_question',None)
        raise BackendError('這次問答尚未完成；稍後重試會優先接續同一個請求。')

    def history(self):return self.request('GET','/v1/history')['records']

    def image(self,asset_id):
        try:
            r=requests.get(self.url+'/v1/media/'+asset_id,headers={'Authorization':'Bearer '+self.key},timeout=(10,30),allow_redirects=False)
            if r.status_code==200 and r.headers.get('Content-Type','').startswith('image/') and len(r.content)<=8*1024*1024:return r.content
        except requests.RequestException:pass
        return None

def get_client():return Client()

class RemoteNotes:
    def __init__(self,path=None):self.client=get_client()
    def list(self,query='',species='全部魚種',topic='全部主題'):
        return self.client.request('GET','/v1/notes',params={'query':query,'species':species,'topic':topic})['notes']
    def get(self,note_id):return next((r for r in self.list() if r['note_id']==note_id),None)
    def save(self,title,body,species='通用',topic='其他',note_id=None,origin='PERSONAL_NOTE',provenance=None):
        if not str(title).strip() or not str(body).strip():raise ValueError('請填寫標題與小知識內容。')
        return self.client.request('POST','/v1/notes',json={'title':title,'body':body,'species':species,'topic':topic,'note_id':note_id,'origin':origin,'provenance':provenance or {}})['note_id']
