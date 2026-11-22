import collections, concurrent.futures, datetime as dt, json, pathlib, time, urllib.error, urllib.parse, urllib.request

ROOT=pathlib.Path.cwd(); OUT=ROOT/'reports/evaluation/fish_test_phase_i_20261014_195032'
H=ROOT/'reports/evaluation/fish_test_phase_h/20261014_185653'
MAPPING=H/'source_mapping_recovery_180.jsonl'
MAX_READ=2*1024*1024

def jl(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
rows=jl(MAPPING)
url_to_q=collections.defaultdict(set)
qid_local=set()
for r in rows:
 qid=r['question_id']
 if any(f.get('exists') and f.get('checksum_match') for f in r.get('local_originals') or []): qid_local.add(qid)
 for u in r.get('source_urls') or []:
  if isinstance(u,str) and u.startswith(('https://','http://')): url_to_q[u].add(qid)
hosts=collections.defaultdict(list)
for url in sorted(url_to_q):
 try: host=urllib.parse.urlsplit(url).hostname or ''
 except Exception: host=''
 hosts[host].append(url)

def probe(url):
 started=dt.datetime.now(dt.timezone.utc).isoformat()
 req=urllib.request.Request(url,headers={'User-Agent':'MarineHybridRAG-SourceAudit/1.0 (read-only source locator verification)','Accept':'text/html,application/pdf,application/xml,text/xml,*/*'},method='GET')
 try:
  with urllib.request.urlopen(req,timeout=10) as resp:
   content_type=resp.headers.get('Content-Type'); length=resp.headers.get('Content-Length')
   body=resp.read(MAX_READ+1); truncated=len(body)>MAX_READ
   if truncated: body=body[:MAX_READ]
   final=resp.geturl(); status=resp.status
   if body.startswith(b'%PDF-'): fmt='pdf'
   elif body.lstrip().lower().startswith((b'<!doctype html',b'<html')) or 'text/html' in (content_type or '').lower(): fmt='html'
   elif b'<?xml' in body[:200] or 'xml' in (content_type or '').lower(): fmt='xml'
   else: fmt='other'
   direct_original=fmt in {'pdf','xml'} or (fmt=='html' and not truncated and (not length or int(length)<=MAX_READ))
   return {'url':url,'final_url':final,'host':urllib.parse.urlsplit(url).hostname,'http_status':status,'content_type':content_type,'content_length_header':length,
    'bytes_read':len(body),'probe_truncated':truncated,'detected_format':fmt,'pdf_signature_valid':fmt=='pdf','landing_or_resource_retrievable':True,
    'complete_original_content_retrieved':bool(direct_original),'sha256':'not_computed_probe_only','saved_to_staging':False,
    'license_status':'not_established_by_reachability_probe','terms_checked':False,'accessed_at':started,'error':None}
 except urllib.error.HTTPError as e:
  return {'url':url,'final_url':e.geturl(),'host':urllib.parse.urlsplit(url).hostname,'http_status':e.code,'content_type':e.headers.get('Content-Type') if e.headers else None,
    'content_length_header':e.headers.get('Content-Length') if e.headers else None,'bytes_read':0,'probe_truncated':False,'detected_format':'unavailable',
    'pdf_signature_valid':False,'landing_or_resource_retrievable':False,'complete_original_content_retrieved':False,'sha256':'not_computed_probe_only',
    'saved_to_staging':False,'license_status':'not_established_by_reachability_probe','terms_checked':False,'accessed_at':started,'error':f'HTTPError {e.code}: {str(e)[:300]}'}
 except Exception as e:
  return {'url':url,'final_url':None,'host':urllib.parse.urlsplit(url).hostname,'http_status':None,'content_type':None,'content_length_header':None,
    'bytes_read':0,'probe_truncated':False,'detected_format':'unavailable','pdf_signature_valid':False,'landing_or_resource_retrievable':False,
    'complete_original_content_retrieved':False,'sha256':'not_computed_probe_only','saved_to_staging':False,'license_status':'not_established_by_reachability_probe',
    'terms_checked':False,'accessed_at':started,'error':f'{type(e).__name__}: {str(e)[:300]}'}

def host_worker(items):
 results=[]
 for i,url in enumerate(items):
  if i: time.sleep(2)
  results.append(probe(url))
 return results

results=[]
# Keep at most three independent hosts active, while spacing requests to each host by >=2 seconds.
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 futs=[ex.submit(host_worker,urls) for urls in hosts.values()]
 for f in concurrent.futures.as_completed(futs): results.extend(f.result())
results.sort(key=lambda x:x['url'])
byurl={r['url']:r for r in results}
out=[]
for url, qs in sorted(url_to_q.items()):
 r=byurl[url].copy(); r['question_ids']=sorted(qs); r['mapped_question_count']=len(qs); out.append(r)
with (OUT/'source_url_accessibility_probe_50.jsonl').open('w',encoding='utf-8',newline='\n') as f:
 for r in out: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
summary={'question_records':len(rows),'questions_with_local_original_checksum_match':len(qid_local),'questions_without_verified_local_original':len(rows)-len(qid_local),
 'unique_source_urls':len(url_to_q),'host_count':len(hosts),'probed_urls':len(out),
 'landing_or_resource_retrievable_urls':sum(x['landing_or_resource_retrievable'] for x in out),
 'complete_original_content_retrieved_urls':sum(x['complete_original_content_retrieved'] for x in out),
 'direct_pdf_bytes_observed':sum(x['pdf_signature_valid'] for x in out),
 'unavailable_urls':sum(not x['landing_or_resource_retrievable'] for x in out),
 'license_status':'No license was inferred from HTTP reachability; each URL remains rights-unreviewed unless separately evidenced.',
 'saved_to_staging':False,'probe_only_no_persistent_download':True,
 'status_counts':dict(collections.Counter(str(x['http_status']) if x['http_status'] is not None else 'network_error' for x in out)),
 'format_counts':dict(collections.Counter(x['detected_format'] for x in out))}
(OUT/'source_url_accessibility_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))

