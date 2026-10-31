$ErrorActionPreference = 'Stop'
$taskUrl = 'http://127.0.0.1:8777'
try { $taskStatus = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 3 }
catch { $taskStatus = Invoke-RestMethod -Uri "$taskUrl/api/status" -TimeoutSec 5 }
if ($taskStatus.app -ne 'shortlist-local') { throw 'This port does not belong to Shortlist.' }
Invoke-RestMethod -Method Post -Uri "$taskUrl/api/shutdown" -Headers @{'X-Shortlist'='1'} -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null
Write-Output 'Shortlist is shutting down its app and owned model runtime.'
