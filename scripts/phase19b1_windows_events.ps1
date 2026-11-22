# Read-only forensic collection. No policy update/remove/refresh or security configuration commands.
$ErrorActionPreference = 'Stop'
$recoveryRoot = Join-Path $PSScriptRoot '../reports/evaluation/edge/phase19B_runtime_recovery'
$recoveryRoot = [System.IO.Path]::GetFullPath($recoveryRoot)
$utf8 = [System.Text.UTF8Encoding]::new($false)
$minimal = Get-Content -LiteralPath (Join-Path $recoveryRoot 'minimal_failure.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$previous = Get-Content -LiteralPath (Join-Path $recoveryRoot '../phase19B/runtime_preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$eventPath = Join-Path $recoveryRoot 'windows_code_integrity_events.jsonl'
if (Test-Path -LiteralPath $eventPath) { throw 'Event evidence already exists; do not overwrite' }
$windows = @(
    @{name='minimal_reproduction';start=([DateTimeOffset]::Parse($minimal.started_at)).UtcDateTime.AddMinutes(-2);end=([DateTimeOffset]::Parse($minimal.ended_at)).UtcDateTime.AddMinutes(2)},
    @{name='phase19B_failure';start=([DateTimeOffset]::Parse($previous.timestamp)).UtcDateTime.AddMinutes(-2);end=([DateTimeOffset]::Parse($previous.timestamp)).UtcDateTime.AddMinutes(2)}
)
$logs = @('Microsoft-Windows-CodeIntegrity/Operational', 'Microsoft-Windows-AppLocker/EXE and DLL',
          'Microsoft-Windows-AppLocker/MSI and Script', 'Microsoft-Windows-Windows Defender/Operational')
$status = [System.Collections.Generic.List[object]]::new()
$seen = @{}
$eventsOut = [System.Collections.Generic.List[string]]::new()
foreach ($window in $windows) {
    foreach ($logName in $logs) {
        try {
            $events = @(Get-WinEvent -FilterHashtable @{LogName=$logName;StartTime=$window.start;EndTime=$window.end} -MaxEvents 2000 -ErrorAction Stop)
            $status.Add(@{window=$window.name;log=$logName;status='collected';count=$events.Count;start=$window.start.ToString('o');end=$window.end.ToString('o');capped=($events.Count -eq 2000)})
            foreach ($event in $events) {
                $key = $logName + ':' + $event.RecordId
                if ($seen.ContainsKey($key)) { continue }
                $seen[$key] = $true
                $xml = $event.ToXml()
                try { $message=$event.Message } catch { $message=$null }
                $row = [ordered]@{capture_window=$window.name;log_name=$logName;event_id=$event.Id;record_id=$event.RecordId;timestamp=$event.TimeCreated.ToUniversalTime().ToString('o');provider=$event.ProviderName;message=$message;level=$event.Level;raw_event_xml=$xml}
                $eventsOut.Add(($row | ConvertTo-Json -Depth 10 -Compress))
            }
        } catch {
            $empty = $_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*'
            $status.Add(@{window=$window.name;log=$logName;status=$(if ($empty) {'no_events'} else {'unavailable'});count=0;error=$_.Exception.Message;error_id=$_.FullyQualifiedErrorId})
        }
    }
}
# Capture policy activation history separately; an unchanged file hash is not policy-state evidence.
try {
    $since = [datetime]'2026-10-04T14:00:00Z'
    $activated = @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational';Id=3099;StartTime=$since} -MaxEvents 2000 -ErrorAction Stop)
    $activationRows = @($activated | ForEach-Object { @{event_id=$_.Id;record_id=$_.RecordId;timestamp=$_.TimeCreated.ToUniversalTime().ToString('o');provider=$_.ProviderName;message=$_.Message;raw_event_xml=$_.ToXml()} })
    $activationStatus=@{status='collected';count=$activated.Count;capped=($activated.Count -eq 2000);since=$since.ToUniversalTime().ToString('o')}
} catch { $activationRows=@();$activationStatus=@{status='unavailable_or_no_events';error=$_.Exception.Message;error_id=$_.FullyQualifiedErrorId} }
[System.IO.File]::WriteAllLines($eventPath,$eventsOut,$utf8)
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'event_capture_status.json'),($status | ConvertTo-Json -Depth 10),$utf8)
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'policy_activation_events.json'),(@{status=$activationStatus;events=$activationRows}|ConvertTo-Json -Depth 10),$utf8)
$policyState = [ordered]@{timestamp=[datetime]::UtcNow.ToString('o');read_only=$true}
try { $policyText = (& "$env:WINDIR/System32/CiTool.exe" -lp -json 2>&1 | Out-String);$policyState.citool_exit_code=$LASTEXITCODE;$policyState.citool_raw=$policyText;try {$policyState.citool=$policyText|ConvertFrom-Json} catch {$policyState.citool_parse_error=$_.Exception.Message} } catch {$policyState.citool_error=$_.Exception.Message}
try {$ci=Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy';$policyState.CI_policy_registry=@{VerifiedAndReputablePolicyState=$ci.VerifiedAndReputablePolicyState}} catch {$policyState.registry_error=$_.Exception.Message}
try {$policyState.DeviceGuard=@(Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName 'Win32_DeviceGuard' | Select-Object CodeIntegrityPolicyEnforcementStatus,UsermodeCodeIntegrityPolicyEnforcementStatus,SecurityServicesConfigured,SecurityServicesRunning)} catch {$policyState.DeviceGuard_error=$_.Exception.Message}
try {$policyState.Defender=Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled,IsTamperProtected,AMProductVersion,AntivirusSignatureVersion} catch {$policyState.Defender_error=$_.Exception.Message}
try {$policyState.active_policy_files=@(Get-ChildItem -LiteralPath "$env:WINDIR/System32/CodeIntegrity/CiPolicies/Active" -File | ForEach-Object {@{path=$_.FullName;size=$_.Length;mtime=$_.LastWriteTimeUtc.ToString('o');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})} catch {$policyState.policy_file_read_error=$_.Exception.Message}
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'windows_policy_state.json'),($policyState|ConvertTo-Json -Depth 15),$utf8)
[System.IO.File]::WriteAllText((Join-Path $recoveryRoot 'collector_execution_identity.json'),(@{process_id=$PID;administrator=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);PS_version=$PSVersionTable.PSVersion.ToString();read_only=$true}|ConvertTo-Json),$utf8)
Write-Output ("Preserved raw events: " + $eventsOut.Count)
Write-Output ($status | ConvertTo-Json -Depth 8)
