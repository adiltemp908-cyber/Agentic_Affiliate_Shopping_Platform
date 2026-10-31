param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskUrl = 'http://127.0.0.1:8777'
function Get-ShortlistHealth {
    try { Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 2 }
    catch { Invoke-RestMethod -Uri "$taskUrl/api/status" -TimeoutSec 5 }
}
try {
    $taskStatus = Get-ShortlistHealth
} catch {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + (Join-Path $PSScriptRoot 'run.ps1') + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $taskStatus = Get-ShortlistHealth; break } catch { }
    }
}
if (-not $taskStatus -or $taskStatus.app -ne 'shortlist-local') { throw 'Shortlist did not start or its port is occupied. Run run.ps1 to inspect the error.' }
if (-not $NoBrowser) { Start-Process $taskUrl }

