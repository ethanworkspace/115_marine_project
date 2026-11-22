import os,sys,json,socket,urllib.request,urllib.error,urllib.parse,tempfile,shutil
from pathlib import Path
root=Path(r'C:\my project\115_marine_project')
out=root/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step3b_source_review/tmp'
out.mkdir(parents=True,exist_ok=True)
proxy_rows=[]
for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy'):
 v=os.environ.get(key)
 if v:
  if 'NO_PROXY' in key.upper(): proxy_rows.append({'name':key,'configured':True,'value_redacted':True})
  else:
   u=urllib.parse.urlsplit(v if '://' in v else '//'+v)
   try: port=u.port
   except ValueError: port=None
   proxy_rows.append({'name':key,'configured':True,'scheme':u.scheme or None,'host':u.hostname,'port':port,'credentials_present':bool(u.username or u.password),'value_redacted':True})
 else: proxy_rows.append({'name':key,'configured':False})
hosts=['www.fa.gov.tw','www.tfrin.gov.tw','law.moa.gov.tw']
dns=[]
for h in hosts:
 try: dns.append({'host':h,'status':'resolved','addresses':sorted({x[4][0] for x in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)})})
 except Exception as e:dns.append({'host':h,'status':'failed','exception_type':type(e).__name__,'errno':getattr(e,'errno',None),'message':str(e)})
proxy_connect={'host':'127.0.0.1','port':9}
try:
 with socket.create_connection(('127.0.0.1',9),timeout=3): proxy_connect.update({'status':'connected'})
except Exception as e:proxy_connect.update({'status':'failed','exception_type':type(e).__name__,'errno':getattr(e,'errno',None),'winerror':getattr(e,'winerror',None),'message':str(e),'stage':'proxy_tcp_connect'})
urls=['https://www.fa.gov.tw/view.php?id=385&print=Y&subtheme=&theme=web_structure','https://www.tfrin.gov.tw/ws.php?id=246','https://law.moa.gov.tw/LawContent.aspx?id=FL035443&media=print']
requests=[]
for u in urls:
 host=urllib.parse.urlsplit(u).hostname
 try:
  req=urllib.request.Request(u,method='HEAD',headers={'User-Agent':'Phase20.1E-Step3B-source-review/1.0'})
  with urllib.request.urlopen(req,timeout=4) as r:requests.append({'host':host,'method':'HEAD','status':'success','http_status':r.status,'stage':'HTTP'})
 except Exception as e:
  chain=[]; cur=e
  for _ in range(4):
   if cur is None:break
   chain.append({'type':type(cur).__name__,'errno':getattr(cur,'errno',None),'winerror':getattr(cur,'winerror',None),'message':str(cur)[:300]})
   cur=cur.__cause__ or cur.__context__
  err=e.reason if isinstance(e,urllib.error.URLError) else e
  stage='proxy_tcp_connect' if isinstance(err,OSError) and getattr(err,'winerror',None)==10061 else 'proxy_or_transport'
  requests.append({'host':host,'method':'HEAD','status':'failed','http_status':None,'stage':stage,'exception_type':type(e).__name__,'reason_type':type(err).__name__,'reason_winerror':getattr(err,'winerror',None),'reason_errno':getattr(err,'errno',None),'chain':chain})
temp=out/'temp_probe_root'; temp.mkdir(exist_ok=True)
temp_result={'root':str(temp),'directory_create':False,'nested_file_write_read':False,'file_delete':False,'directory_cleanup':False,'temporary_directory_api':None,'error':None}
child=temp/'controlled';
try:
 child.mkdir(); temp_result['directory_create']=True
 f=child/'probe.tmp'; f.write_text('step3b-temp-probe-fixed-value',encoding='utf-8'); temp_result['nested_file_write_read']=f.read_text(encoding='utf-8')=='step3b-temp-probe-fixed-value'; f.unlink(); temp_result['file_delete']=not f.exists(); child.rmdir(); temp_result['directory_cleanup']=not child.exists()
 try:
  with tempfile.TemporaryDirectory(dir=temp) as td:
   q=Path(td)/'nested';q.mkdir();(q/'x').write_text('x',encoding='utf-8'); temp_result['temporary_directory_api']='pass'
 except Exception as e:temp_result['temporary_directory_api']='fail';temp_result['temporary_directory_error']={'type':type(e).__name__,'errno':getattr(e,'errno',None),'winerror':getattr(e,'winerror',None),'message':str(e)}
except Exception as e:temp_result['error']={'type':type(e).__name__,'errno':getattr(e,'errno',None),'winerror':getattr(e,'winerror',None),'message':str(e)}
finally:
 try: shutil.rmtree(temp)
 except Exception as e:temp_result['root_cleanup_error']={'type':type(e).__name__,'errno':getattr(e,'errno',None),'winerror':getattr(e,'winerror',None),'message':str(e)}
diag={'checked_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'proxy_settings':proxy_rows,'dns_tests':dns,'proxy_tcp_connect':proxy_connect,'official_url_head_tests':requests,'temp_probe':temp_result,'no_credentials_logged':True,'no_direct_proxy_bypass_attempted':True}
(out/'acquisition_and_temp_diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(diag,ensure_ascii=False,indent=2))
