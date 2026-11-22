import os, sys, json, pathlib, tempfile, traceback
base=pathlib.Path(sys.argv[1]).resolve()
pytemp=base/'python_temp'; base_dir=base/'pytest_base'; test=base/'test_temp_fixture_probe.py'
for k in ('TEMP','TMP','TMPDIR'): os.environ[k]=str(pytemp)
tempfile.tempdir=None
out={'interpreter':sys.executable,'tempfile_gettempdir':None,'temporary_directory':'not_run','pytest_fixture':'not_run','tracebacks':{}}
try:
 out['tempfile_gettempdir']=tempfile.gettempdir()
 with tempfile.TemporaryDirectory(prefix='phase20_1e_probe_') as d:
  p=pathlib.Path(d)/'probe.txt'; p.write_text('phase20_1e_exec_r3_temp_probe',encoding='utf-8'); out['temporary_directory']='write_read_pass' if p.read_text(encoding='utf-8')=='phase20_1e_exec_r3_temp_probe' else 'readback_mismatch'; p.unlink()
 out['temporary_directory_cleanup']='pass'
except Exception as e:
 out['temporary_directory']='fail'; out['tracebacks']['temporary_directory']=traceback.format_exc()
try:
 import pytest
 code=pytest.main(['-q','--basetemp',str(base_dir),str(test)])
 out['pytest_exit_code']=int(code)
 out['pytest_fixture']='pass' if int(code)==0 else 'fail'
except Exception as e:
 out['pytest_fixture']='fail'; out['tracebacks']['pytest']=traceback.format_exc()
print(json.dumps(out,ensure_ascii=False,indent=2))
