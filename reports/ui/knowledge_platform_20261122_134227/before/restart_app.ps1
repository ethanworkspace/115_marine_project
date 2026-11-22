$ErrorActionPreference = 'Stop'
$sessionDir = $PSScriptRoot
$projectDir = 'C:\my project\115_marine_project'
$info = Get-Content -LiteralPath (Join-Path $sessionDir 'launch_info.json') -Raw | ConvertFrom-Json
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = 'C:\my project\115_marine_project\.venv-reranker\Lib\site-packages;C:\my project\115_marine_project\.venv\Lib\site-packages'
$env:RAG_APP_PROCESS_ID = [string]$info.pid
$env:RAG_APP_ENTRY = Join-Path $sessionDir 'run_app.py'
& $info.interpreter -B -c "import os,psutil; expected=os.environ['RAG_APP_ENTRY']; ident=int(os.environ['RAG_APP_PROCESS_ID']); p=psutil.Process(ident) if psutil.pid_exists(ident) else None; assert p is None or expected in p.cmdline(), 'Process does not belong to this app'; targets=([x for x in p.children(recursive=True) if expected in x.cmdline()]+[p]) if p else []; [x.terminate() for x in targets]; _,alive=psutil.wait_procs(targets,timeout=5); [x.kill() for x in alive if expected in x.cmdline()]; print('Previous app stopped')"
if ($LASTEXITCODE -ne 0) { throw 'App ownership check failed; no other process will be stopped.' }
$stamp = Get-Date -Format 'HHmmss'
$launchArgs = @('-B','-m','streamlit','run',('"'+$env:RAG_APP_ENTRY+'"'),'--server.address','127.0.0.1','--server.port','8501','--server.headless','true','--server.fileWatcherType','none','--browser.gatherUsageStats','false','--theme.base','light','--theme.primaryColor','#0D827C','--theme.backgroundColor','#F4F7FA','--theme.secondaryBackgroundColor','#F0F5F7','--theme.textColor','#153247')
$proc = Start-Process -FilePath $info.interpreter -ArgumentList $launchArgs -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $sessionDir ('stdout_platform_'+$stamp+'.log')) -RedirectStandardError (Join-Path $sessionDir ('stderr_platform_'+$stamp+'.log')) -PassThru
$info.pid = $proc.Id
$info | Add-Member -NotePropertyName interface_style -NotePropertyValue 'professional_knowledge_platform' -Force
$info | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sessionDir 'launch_info.json') -Encoding utf8
Write-Output ('Application PID: '+$proc.Id)
