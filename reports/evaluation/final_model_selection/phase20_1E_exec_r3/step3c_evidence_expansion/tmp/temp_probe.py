import tempfile, pathlib, os, json
root=pathlib.Path(tempfile.gettempdir())
result={'tempfile_gettempdir':str(root),'temp_env':{k:os.environ.get(k) for k in ('TEMP','TMP','TMPDIR')},'temp_directory_created':False,'write_read_cleanup':False,'temporary_directory_cleanup':False,'error':None}
try:
 with tempfile.TemporaryDirectory(prefix='phase20_1e_probe_') as d:
  p=pathlib.Path(d)/'probe.txt'; p.write_text('phase20_1e_exec_r3_temp_probe',encoding='utf-8'); result['temp_directory_created']=True; result['write_read_cleanup']=(p.read_text(encoding='utf-8')=='phase20_1e_exec_r3_temp_probe'); p.unlink(); result['temporary_directory_cleanup']=not pathlib.Path(d).exists()
except Exception as e:
 result['error']=repr(e)
print(json.dumps(result,ensure_ascii=False))
