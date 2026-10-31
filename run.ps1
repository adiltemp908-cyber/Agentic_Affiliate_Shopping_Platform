$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
python -m shortlist serve

