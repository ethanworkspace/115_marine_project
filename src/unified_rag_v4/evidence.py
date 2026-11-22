"""Program-bound source spans: the generator never authors original quotations."""
import copy
import hashlib
import re

def span_registry(contexts):
    out={}
    for chunk in contexts:
        text=chunk['source_quote'];breaks=[0]+[m.end() for m in re.finditer(r'[。！？；;\n]',text)]+[len(text)]
        breaks=sorted(set(breaks));start=0
        ranges=[]
        for end in breaks[1:]:
            if end-start>=220:
                ranges.append((start,end));start=end
        if start<len(text):
            if ranges and len(text)-start<8: ranges[-1]=(ranges[-1][0],len(text))
            else: ranges.append((start,len(text)))
        for start,end in ranges:
            if not text[start:end].strip(): continue
            sid='E'+hashlib.sha256((chunk['chunk_id']+':'+str(start)+':'+str(end)).encode()).hexdigest()[:9]
            out[sid]={'span_id':sid,'chunk_id':chunk['chunk_id'],'quote':text[start:end],'start_in_source_quote':start,'end_in_source_quote':end,'start_in_chunk':chunk['text'].find(text)+start,'end_in_chunk':chunk['text'].find(text)+end}
    return out

def output_schema(base,ids,spans,insufficient=False):
    schema=copy.deepcopy(base)
    schema['properties'].pop('supporting_chunk_ids',None)
    schema['required']=[k for k in schema['required'] if k!='supporting_chunk_ids']
    schema['properties']['answer']['minLength']=1
    if insufficient: schema['properties']['answer_status']['enum']=['INSUFFICIENT_EVIDENCE']
    else: schema['properties']['answer_status']['enum']=['ANSWERED_PARTIAL','INSUFFICIENT_EVIDENCE']
    schema['properties']['evidence']={'type':'array','maxItems':5,'items':{'type':'object','properties':{'span_ids':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'string','enum':list(spans)} if spans else {'type':'string'}},'supported_answer_element':{'type':'string','minLength':1,'maxLength':120}},'required':['span_ids','supported_answer_element'],'additionalProperties':False}}
    schema['required'].append('evidence')
    if not ids:
        schema['properties']['evidence']['maxItems']=0
    return schema

def bind_quotes(parsed,registry,contexts):
    result=copy.deepcopy(parsed);byid={c['chunk_id']:c for c in contexts};checks=[];groups={}
    for item in parsed['evidence']:
        for sid in item['span_ids']:
            span=registry.get(sid)
            if not span: raise ValueError('INVALID_SPAN_ID')
            cid=span['chunk_id']
            if cid not in byid: raise ValueError('CHUNK_NOT_IN_ALLOWED_CONTEXT')
            text=byid[cid]['source_quote'];a=span['start_in_source_quote'];b=span['end_in_source_quote']
            if text[a:b]!=span['quote']: raise ValueError('SOURCE_SPAN_CHANGED')
            checks.append(span);groups.setdefault(cid,[]).append(item['supported_answer_element'])
    result['evidence']=[];result['supporting_chunk_ids']=list(groups)
    for cid,reasons in groups.items():
        # Include the entire selected semantic unit so its dates, qualifications,
        # table headers and conditions are not lost by a too-short quotation.
        quote=byid[cid]['source_quote']
        if quote not in byid[cid]['text']: raise ValueError('QUOTE_NOT_IN_BOUND_ORIGINAL_CHUNK')
        result['evidence'].append({'chunk_id':cid,'quote':quote,'supported_answer_element':'；'.join(dict.fromkeys(reasons))})
    return result,checks
