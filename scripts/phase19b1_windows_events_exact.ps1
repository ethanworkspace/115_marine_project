# Read only. Explicit UTC XPath avoids Get-WinEvent FilterHashtable local-time ambiguity.
$ErrorActionPreference = 'Stop'
$recoveryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../reports/evaluation/edge/phase19B_runtime_recovery'))
$utf8 = [System.Text.UTF8Encoding]::new($false)
$minimal = Get-Content -LiteralPath (Join-Path $recoveryRoot 'minimal_failure.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$previous = Get-Content -LiteralPath (Join-Path $recoveryRoot '../phase19B/runtime_preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$eventPath = Join-Path $recoveryRoot 'windows_code_integrity_events_exact_utc.jsonl'
if (Test-Path -LiteralPath $eventPath) { throw 'Exact event evidence exists; refuse overwrite' }
$windows = @(
    @{name='minimal_reproduction';start=([DateTimeOffset]::Parse($minimal.started_at)).UtcDateTime.AddMinutes(-2);end=([DateTimeOffset]::Parse($minimal.ended_at)).UtcDateTime.AddMinutes(2)},
    @{name='phase19B_failure';start=([DateTimeOffset]::Parse($previous.timestamp)).UtcDateTime.AddMinutes(-2);end=([DateTimeOffset]::Parse($previous.timestamp)).UtcDateTime.AddMinutes(2)}
)
$logs = @('Microsoft-Windows-CodeIntegrity/Operational','Microsoft-Windows-AppLocker/EXE and DLL','Microsoft-Windows-AppLocker/MSI and Script','Microsoft-Windows-Windows Defender/Operational')
$rows = [System.Collections.Generic.List[string]]::new();$status=[System.Collections.Generic.List[object]]::new();$seen=@{}
foreach ($window in $windows) {
    foreach ($logName in $logs) {
        $start=$window.start.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ");$end=$window.end.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
        $logEsc=[System.Security.SecurityElement]::Escape($logName)
        $filterXml="<QueryList><Query Id='0' Path='$logEsc'><Select Path='$logEsc'>*[System[TimeCreated[@SystemTime&gt;='$start' and @SystemTime&lt;='$end']]]</Select></Query></QueryList>"
        try {
            $events=@(Get-WinEvent -FilterXml $filterXml -MaxEvents 2000 -ErrorAction Stop)
            $status.Add(@{window=$window.name;log=$logName;status='collected';count=$events.Count;start_utc=$start;end_utc=$end;capped=($events.Count -eq 2000);query_xml=$filterXml})
            foreach ($event in $events) {
                $key=$logName+':'+$event.RecordId;if ($seen.ContainsKey($key)) {continue};$seen[$key]=$true
                $xml=$event.ToXml();$parsed=[xml]$xml
                $message=$null;try {$message=$event.Message} catch {}
                $r=[ordered]@{capture_window=$window.name;log_name=$logName;event_id=$event.Id;record_id=$event.RecordId;timestamp=$parsed.Event.System.TimeCreated.SystemTime;provider=$event.ProviderName;message=$message;raw_event_xml=$xml}
                $rows.Add(($r|ConvertTo-Json -Depth 10 -Compress))
            }
        } catch {$status.Add(@{window=$window.name;log=$logName;status=$(if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {'no_events'} else {'unavailable'});count=0;error=$_.Exception.Message;error_id=$_.FullyQualifiedErrorId;query_xml=$filterXml})}
    }
}
[System.IO.File]::WriteAllLines($eventPath,$rows,$utf8)
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'event_capture_status_exact_utc.json'),($status|ConvertTo-Json -Depth 12),$utf8)
$policy=[ordered]@{timestamp=[datetime]::UtcNow.ToString('o');read_only=$true;administrator=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}
try {$policy.citool_raw=(& "$env:WINDIR/System32/CiTool.exe" -lp -json 2>&1|Out-String);$policy.citool_exit_code=$LASTEXITCODE;try {$policy.citool=$policy.citool_raw|ConvertFrom-Json} catch {}} catch {$policy.citool_error=$_.Exception.Message}
try {$policy.DeviceGuard=@(Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName 'Win32_DeviceGuard' -ErrorAction Stop | Select-Object CodeIntegrityPolicyEnforcementStatus,UsermodeCodeIntegrityPolicyEnforcementStatus,SecurityServicesConfigured,SecurityServicesRunning)} catch {$policy.DeviceGuard_error=$_.Exception.Message}
try {$policy.Defender=Get-MpComputerStatus -ErrorAction Stop | Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled,IsTamperProtected,AMProductVersion,AntivirusSignatureVersion} catch {$policy.Defender_error=$_.Exception.Message}
try {$ci=Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy';$policy.CI_policy_registry=@{VerifiedAndReputablePolicyState=$ci.VerifiedAndReputablePolicyState}} catch {$policy.registry_error=$_.Exception.Message}
$activationXml="<QueryList><Query Id='0' Path='Microsoft-Windows-CodeIntegrity/Operational'><Select Path='Microsoft-Windows-CodeIntegrity/Operational'>*[System[EventID=3099 and TimeCreated[@SystemTime&gt;='2026-10-04T14:00:00.0000000Z']]]</Select></Query></QueryList>"
try {$activation=@(Get-WinEvent -FilterXml $activationXml -MaxEvents 2000 -ErrorAction Stop);$policy.activation_events=@($activation|ForEach-Object {@{event_id=$_.Id;record_id=$_.RecordId;raw_event_xml=$_.ToXml();message=$_.Message}})} catch {$policy.activation_error=$_.Exception.Message}
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'windows_policy_state_exact_capture.json'),($policy|ConvertTo-Json -Depth 15),$utf8)
Write-Output (@{events=$rows.Count;administrator=$policy.administrator;citool_exit=$policy.citool_exit_code}|ConvertTo-Json)
