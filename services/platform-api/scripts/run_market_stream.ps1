$ErrorActionPreference = 'Stop'

$ApiRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$Worker = Join-Path $PSScriptRoot 'run_market_stream.py'
$LogDirectory = Join-Path $ApiRoot 'logs'
$LogFile = Join-Path $LogDirectory 'market-stream.log'

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing virtual environment: $PythonExe" }
if (-not (Test-Path -LiteralPath (Join-Path $ApiRoot '.env'))) { throw 'Missing platform-api .env file' }

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
Set-Location -LiteralPath $ApiRoot
"$(Get-Date -Format o) market stream worker starting" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
& $PythonExe $Worker *>> $LogFile
exit $LASTEXITCODE
