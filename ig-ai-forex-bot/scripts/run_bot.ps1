$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$LogDirectory = Join-Path $ProjectRoot 'logs'
$LogFile = Join-Path $LogDirectory 'service.log'

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Virtual environment Python was not found: $PythonExe"
}

"$(Get-Date -Format o) service runner starting" | Out-File -FilePath $LogFile -Append -Encoding utf8
& $PythonExe -m forexbot.cli check *>> $LogFile
if ($LASTEXITCODE -ne 0) {
    throw "IG API preflight failed. Review $LogFile"
}

& $PythonExe -m forexbot.cli run *>> $LogFile
exit $LASTEXITCODE
