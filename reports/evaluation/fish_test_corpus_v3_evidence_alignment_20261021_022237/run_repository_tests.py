from pathlib import Path
import sys,json,datetime,subprocess,os
W=Path(__file__).resolve().parent
R=W.parents[2]
paths=[str(R/'.venv-reranker/Lib/site-packages'),str(R/'.venv/Lib/site-packages')]
env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(paths+[str(R)])
env['PYTHONIOENCODING']='utf-8'
cmd=[str(W/'test_env/Scripts/python.exe'),'-m','pytest','tests/','-q','-p','no:cacheprovider','--basetemp',str(W/'pytest_temp_final')]
with (W/'test_logs/repository_pytest_final.log').open('w',encoding='utf-8') as f:
 p=subprocess.run(cmd,cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT)
log=(W/'test_logs/repository_pytest_final.log').read_text(encoding='utf-8')
versions=subprocess.run([cmd[0],'-c',"import sys,pytest,torch,scipy,docx,pymupdf;print(sys.executable);print(sys.version);print('pytest',pytest.__version__,'torch',torch.__version__,'scipy',scipy.__version__,'docx',docx.__version__,'pymupdf',pymupdf.__version__)"],cwd=R,env=env,capture_output=True,text=True,encoding='utf-8')
out={'command':cmd,'exit_code':p.returncode,'interpreter':cmd[0],'base_interpreter':'C:/Users/ethan/anaconda3/python.exe','environment':'new venv with system site packages; existing parser/reranker packages read-only via explicit PYTHONPATH','dependency_paths':paths,'version_output':versions.stdout,'version_error':versions.stderr,'log':str(W/'test_logs/repository_pytest_final.log'),'summary_lines':[s for s in log.splitlines() if any(t in s for t in [' passed',' failed',' skipped','ERROR','collected'])][-30:],'production_environment_modified':False}
(W/'repository_pytest_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=True))

