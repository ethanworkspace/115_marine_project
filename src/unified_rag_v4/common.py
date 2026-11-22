from __future__ import annotations
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
import numpy as np
import requests

EMBED_MODEL = 'bge-m3:latest'
EMBED_DIGEST = '7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'
FISH = {
    '虱目魚': ('虱目魚', 'Chanos chanos'),
    '吳郭魚': ('吳郭魚', '臺灣鯛', '台灣鯛', '羅非魚', 'Oreochromis', 'tilapia'),
    '石斑魚': ('石斑魚', '石斑', '鞍帶石斑', '龍膽石斑', 'Epinephelus'),
    '鱸魚': ('鱸魚', '金目鱸', '七星鱸', 'Lates calcarifer', 'Lateolabrax'),
    '烏魚': ('烏魚', '鯔魚', 'Mugil cephalus'),
    '鰻魚': ('鰻魚', '白鰻', '日本鰻', '臺灣鰻', '台灣鰻', 'Anguilla'),
}
NARROW = ('金目鱸','七星鱸','鞍帶石斑','龍膽石斑','白鰻','日本鰻','歐洲鰻','美洲鰻')

def sha_file(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def digest(value):
    if not isinstance(value, bytes): value=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(value).hexdigest()

def dump(path, obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def clean(text):
    # No guessed fish-name correction and no NFKC conversion of scientific units.
    text=unicodedata.normalize('NFC',str(text)).replace('\x00','').replace('\r\n','\n').replace('\r','\n')
    text=re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text=re.sub(r'[\t\u3000 ]+', ' ', text)
    return '\n'.join(s.strip() for s in text.splitlines()).strip()

def species(text):
    found=[fish for fish, aliases in FISH.items() if any(alias.casefold() in text.casefold() for alias in aliases)]
    return list(dict.fromkeys(found+[n for n in NARROW if n in text]))

def tokens(text):
    letters=re.sub(r'\s+', '', text.casefold())
    cjk=''.join(re.findall(r'[\u3400-\u9fff]',letters))
    return ' '.join(list(cjk)+[cjk[i:i+2] for i in range(max(0,len(cjk)-1))]+re.findall(r'[a-z0-9]+',letters))

def embed(texts, retries=2):
    if not texts: return np.empty((0,1024),dtype=np.float32)
    for attempt in range(retries+1):
        try:
            r=requests.post('http://127.0.0.1:11434/api/embed',json={'model':EMBED_MODEL,'input':texts,'truncate':False,'keep_alive':'30m'},timeout=(15,240))
            r.raise_for_status(); a=np.asarray(r.json()['embeddings'],dtype=np.float32)
            if a.shape!=(len(texts),1024) or not np.isfinite(a).all(): raise ValueError('Invalid BGE-M3 shape or nonfinite embedding')
            return a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12)
        except Exception:
            if attempt==retries: raise
            time.sleep(min(2**attempt,4))

def verify_embedding_model():
    data=requests.get('http://127.0.0.1:11434/api/tags',timeout=20).json()
    got=next(x for x in data['models'] if x['name']==EMBED_MODEL)
    if got['digest']!=EMBED_DIGEST: raise ValueError('BGE-M3 digest changed')
    return got
