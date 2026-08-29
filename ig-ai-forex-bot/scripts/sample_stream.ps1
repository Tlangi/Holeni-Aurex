param(
    [ValidateRange(10, 300)]
    [int]$Seconds = 60
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Project Python was not found: $PythonExe. Create the virtual environment and install requirements first."
}

Set-Location -LiteralPath $ProjectRoot
Write-Output "Starting prices-only IG demo sample for $Seconds seconds. This command cannot place trades."
& $PythonExe -m forexbot.cli sample-stream --sample-seconds $Seconds
if ($LASTEXITCODE -ne 0) {
    throw "Sample streaming failed with exit code $LASTEXITCODE. Review the concise error above."
}

& $PythonExe -m forexbot.cli cache-status
exit $LASTEXITCODE
