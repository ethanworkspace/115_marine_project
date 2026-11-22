# File identity, signatures, owner/ACL and ADS: read only; never remove Zone.Identifier.
$ErrorActionPreference='Stop'
$recoveryRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../reports/evaluation/edge/phase19B_runtime_recovery'))
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output=Join-Path $recoveryRoot 'blocked_file_identity.json'
if (Test-Path -LiteralPath $output) {throw 'File identity evidence already exists'}
$lib=Join-Path $projectRoot '.venv-reranker/Lib/site-packages/torch/lib'
$paths=@('shm.dll','c10.dll','c10_cuda.dll','torch_cpu.dll','torch_cuda.dll')|ForEach-Object {Join-Path $lib $_}
$paths+=Join-Path $projectRoot '.venv-reranker/Scripts/python.exe'
$paths+='C:\Python314\python.exe'
$rows=@()
foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) {$rows+=@{path=$path;exists=$false};continue}
    $file=Get-Item -LiteralPath $path
    $r=[ordered]@{absolute_path=$file.FullName;size=$file.Length;mtime_utc=$file.LastWriteTimeUtc.ToString('o');sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash;exists=$true;observed_as_blocked=($file.Name -eq 'shm.dll')}
    try {$sig=Get-AuthenticodeSignature -LiteralPath $path;$r.signature=@{status=$sig.Status.ToString();status_message=$sig.StatusMessage;signature_type=$sig.SignatureType.ToString();publisher=$sig.SignerCertificate.Subject;certificate_thumbprint=$sig.SignerCertificate.Thumbprint;timestamp_signer=$sig.TimeStamperCertificate.Subject}} catch {$r.signature=@{status='unavailable';error=$_.Exception.Message}}
    try {$acl=Get-Acl -LiteralPath $path;$r.owner=$acl.Owner;$r.ACL_SDDL=$acl.Sddl;$r.ACL_summary=@($acl.Access|Select-Object IdentityReference,FileSystemRights,AccessControlType,IsInherited)} catch {$r.ACL_error=$_.Exception.Message}
    try {$streams=@(Get-Item -LiteralPath $path -Stream * -ErrorAction Stop);$r.streams=@($streams|Select-Object Stream,Length);$zone=$streams|Where-Object Stream -eq 'Zone.Identifier';$r.Zone_Identifier_present=($null -ne $zone);if ($zone) {$r.Zone_Identifier_content=Get-Content -LiteralPath $path -Stream 'Zone.Identifier' -Raw -ErrorAction Stop}} catch {$r.Zone_Identifier_present=$null;$r.stream_error=$_.Exception.Message}
    $rows+=$r
}
[IO.File]::WriteAllText($output,($rows|ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
Write-Output ($rows|ForEach-Object {@{path=$_.absolute_path;signature=$_.signature.status;Zone_Identifier=$_.Zone_Identifier_present;sha256=$_.sha256}}|ConvertTo-Json -Depth 5)
