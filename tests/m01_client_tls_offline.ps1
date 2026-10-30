param([string]$PolicyRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) 'tools/diagnostics'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PolicyRoot 'm01_client_tls.ps1')
$saved=@{}
foreach($k in @('SSL_CERT_FILE','SSL_CERT_DIR','OPENSSL_CONF','OPENSSL_MODULES','PGSSLMODE','PGSSLROOTCERT')) {
    $saved[$k]=[Environment]::GetEnvironmentVariable($k,'Process')
    [Environment]::SetEnvironmentVariable($k,$null,'Process')
}
$passed=New-Object 'System.Collections.Generic.List[string]'
function Expect-Failure([scriptblock]$Action,[string]$Code) {
    $caught=$false
    try { & $Action | Out-Null } catch {
        $caught=$true
        if($_.Exception.Message -cne $Code) { throw 'Unexpected safe TLS policy error code' }
    }
    if(!$caught) {throw 'Expected fail-closed result was not observed'}
}
function New-ChildInfo {
    $p=New-Object Diagnostics.ProcessStartInfo
    $p.EnvironmentVariables['PGPASSWORD']='test-password-canary'
    $p.EnvironmentVariables['PGUSER']='test-user-canary'
    $p.EnvironmentVariables['PGOPTIONS']='-c default_transaction_read_only=on'
    return $p
}
try {
    $policy=Get-M01ClientCaPolicy -PolicyRoot $PolicyRoot
    if($policy.CertificateCount -ne 118 -or !$policy.CaPath) {throw 'Pinned bundle not validated'}
    $passed.Add('pinned_public_bundle')
    $env:SSL_CERT_FILE='parent-file-canary';$env:SSL_CERT_DIR='parent-dir-canary'
    $env:PGSSLMODE='disable';$env:PGSSLROOTCERT='parent-root-canary'
    $child=New-ChildInfo
    $summary=Set-M01ClientTlsEnvironment -StartInfo $child -PolicyRoot $PolicyRoot
    if($child.EnvironmentVariables['PGSSLMODE'] -cne 'verify-full' -or
       $child.EnvironmentVariables['PGSSLROOTCERT'] -cne $policy.CaPath) {throw 'Explicit verify-full CA policy not applied'}
    $passed.Add('child_verify_full_explicit_CA')
    if($child.EnvironmentVariables.ContainsKey('SSL_CERT_FILE') -or $child.EnvironmentVariables.ContainsKey('SSL_CERT_DIR')) {throw 'Child CA conflicts remain'}
    $passed.Add('child_CA_overrides_removed')
    if($env:SSL_CERT_FILE -cne 'parent-file-canary' -or $env:SSL_CERT_DIR -cne 'parent-dir-canary' -or
       $env:PGSSLMODE -cne 'disable' -or $env:PGSSLROOTCERT -cne 'parent-root-canary') {throw 'Parent environment was modified'}
    $passed.Add('parent_environment_preserved')
    if($child.EnvironmentVariables['PGPASSWORD'] -cne 'test-password-canary' -or
       $child.EnvironmentVariables['PGUSER'] -cne 'test-user-canary' -or
       $child.EnvironmentVariables['PGOPTIONS'] -cne '-c default_transaction_read_only=on') {throw 'Authentication/read-only settings changed'}
    $passed.Add('credentials_and_readonly_untouched')
    $json=$summary|ConvertTo-Json -Compress
    if($json -match 'canary|CaPath|ProcessStartInfo|PGPASSWORD|PGUSER') {throw 'Secret or local path leaked in safe evidence'}
    $passed.Add('safe_metadata_only')
    foreach($key in @('OPENSSL_CONF','OPENSSL_MODULES')) {
        $c=New-ChildInfo;$c.EnvironmentVariables[$key]='private-config-canary'
        Expect-Failure {Set-M01ClientTlsEnvironment -StartInfo $c -PolicyRoot $PolicyRoot} 'TLS_POLICY_CUSTOM_OPENSSL_CONFIGURATION_REQUIRES_REVIEW'
        $passed.Add($key+'_fail_closed')
    }
    $temp=Join-Path ([IO.Path]::GetTempPath()) ('m01-ca-policy-'+[Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($temp)
    Copy-Item -LiteralPath (Join-Path $PolicyRoot 'ca') -Destination $temp -Recurse
    $ca=Join-Path $temp 'ca/certifi-2026.10.23.pem'
    [IO.File]::AppendAllText($ca,"`n-----BEGIN PRIVATE KEY-----`nsynthetic-only`n")
    Expect-Failure {Get-M01ClientCaPolicy -PolicyRoot $temp} 'TLS_POLICY_CA_HASH_MISMATCH'
    $passed.Add('tampered_bundle_rejected')
    Copy-Item -LiteralPath $policy.CaPath -Destination $ca -Force
    $manifestPath=Join-Path $temp 'ca/provenance.json'
    $manifest=[IO.File]::ReadAllText($manifestPath)|ConvertFrom-Json
    $manifest.version='unapproved-version'
    [IO.File]::WriteAllText($manifestPath,($manifest|ConvertTo-Json -Depth 7))
    Expect-Failure {Get-M01ClientCaPolicy -PolicyRoot $temp} 'TLS_POLICY_PROVENANCE_MISMATCH'
    $passed.Add('unapproved_manifest_rejected')
    Expect-Failure {Get-M01ClientCaPolicy -PolicyRoot 'relative-private-path'} 'TLS_POLICY_LOCAL_PATH_REQUIRED'
    $passed.Add('relative_path_rejected')
    Expect-Failure {Get-M01ClientCaPolicy -PolicyRoot '\\invalid-private-host\share'} 'TLS_POLICY_LOCAL_PATH_REQUIRED'
    $passed.Add('UNC_path_rejected_before_IO')
    $missing=Join-Path $temp 'does-not-exist'
    Expect-Failure {Get-M01ClientCaPolicy -PolicyRoot $missing} 'TLS_POLICY_CA_FILES_UNAVAILABLE_OR_INVALID'
    $passed.Add('missing_bundle_rejected')
    Write-Output ('M01_CLIENT_TLS_OFFLINE_OK cases='+$passed.Count+' engine='+$PSVersionTable.PSVersion.ToString()+' network_connections=0')
} finally {
    foreach($k in $saved.Keys) {[Environment]::SetEnvironmentVariable($k,$saved[$k],'Process')}
}
