# Local diagnostic transport only. No network, app import, migration or trust-store writes.
function Get-M01ClientCaPolicy {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][string]$PolicyRoot)
    $expectedHash = '2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b'
    try {
        if (![IO.Path]::IsPathRooted($PolicyRoot) -or $PolicyRoot.StartsWith('\\')) {
            throw 'TLS_POLICY_LOCAL_PATH_REQUIRED'
        }
        $root = [IO.Path]::GetFullPath($PolicyRoot)
        $ca = Join-Path $root 'ca/certifi-2026.10.23.pem'
        $manifestPath = Join-Path $root 'ca/provenance.json'
        foreach ($file in @($ca,$manifestPath,(Join-Path $root 'ca/CERTIFI-LICENSE.txt'),(Join-Path $root 'ca/MPL-2.0.txt'))) {
            $item = Get-Item -LiteralPath $file -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'TLS_POLICY_REGULAR_FILE_REQUIRED'
            }
        }
        $hash = (Get-FileHash -LiteralPath $ca -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -cne $expectedHash) { throw 'TLS_POLICY_CA_HASH_MISMATCH' }
        $text = [IO.File]::ReadAllText($ca)
        if ($text -match 'PRIVATE KEY' -or
            [regex]::Matches($text,'-----BEGIN CERTIFICATE-----').Count -ne 118 -or
            [regex]::Matches($text,'-----END CERTIFICATE-----').Count -ne 118) {
            throw 'TLS_POLICY_CA_FORMAT_INVALID'
        }
        $manifest = [IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
        if ($manifest.version -cne '2026.10.23' -or $manifest.bundle_sha256 -cne $expectedHash -or
            $manifest.certificate_count -ne 118 -or $manifest.license -cne 'MPL-2.0' -or
            $manifest.unchanged_from_official_wheel -ne $true) {
            throw 'TLS_POLICY_PROVENANCE_MISMATCH'
        }
        return [pscustomobject]@{CaPath=$ca;Sha256=$hash;Version='2026.10.23';CertificateCount=118}
    } catch {
        if ($_.Exception.Message -like 'TLS_POLICY_*') { throw $_.Exception.Message }
        throw 'TLS_POLICY_CA_FILES_UNAVAILABLE_OR_INVALID'
    }
}

function Set-M01ClientTlsEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory=$true)][string]$PolicyRoot
    )
    # A custom OpenSSL provider/FIPS policy must be reviewed, not silently disabled.
    foreach ($key in @('OPENSSL_CONF','OPENSSL_MODULES')) {
        if (![string]::IsNullOrEmpty($StartInfo.EnvironmentVariables[$key])) {
            throw 'TLS_POLICY_CUSTOM_OPENSSL_CONFIGURATION_REQUIRES_REVIEW'
        }
    }
    $policy = Get-M01ClientCaPolicy -PolicyRoot $PolicyRoot
    $cleared = @()
    foreach ($key in @('SSL_CERT_FILE','SSL_CERT_DIR')) {
        if ($StartInfo.EnvironmentVariables.ContainsKey($key)) {
            $cleared += $key
            $StartInfo.EnvironmentVariables.Remove($key)
        }
    }
    $StartInfo.EnvironmentVariables['PGSSLMODE'] = 'verify-full'
    $StartInfo.EnvironmentVariables['PGSSLROOTCERT'] = $policy.CaPath
    # Return only safe metadata, never ProcessStartInfo or its credentials.
    return [pscustomobject]@{
        scope='PSQL_CHILD_ONLY';sslmode='verify-full';ca_source='certifi/Mozilla'
        ca_version=$policy.Version;ca_sha256=$policy.Sha256;certificate_count=$policy.CertificateCount
        cleared_override_keys=$cleared
    }
}
