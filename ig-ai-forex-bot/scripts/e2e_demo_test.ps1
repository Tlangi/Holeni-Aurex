param(
    [switch]$ExecuteDemoTrade,
    [switch]$StartContinuousTask
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing virtual environment: $PythonExe" }

Set-Location -LiteralPath $ProjectRoot
Write-Output "Running as $Identity"
Write-Output '1/6 Unit tests'
& $PythonExe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }

Write-Output '2/6 IG API demo preflight'
& $PythonExe -m forexbot.cli check
if ($LASTEXITCODE -ne 0) { throw 'IG API preflight failed; no later stage was run' }

Write-Output '3/6 Model training and validation'
& $PythonExe -m forexbot.cli train
if ($LASTEXITCODE -ne 0) { throw 'Training/validation failed; no trade was attempted' }

Write-Output '4/6 Non-trading signal cycle'
& $PythonExe -m forexbot.cli dry-run
if ($LASTEXITCODE -ne 0) { throw 'Dry-run failed; no trade was attempted' }

Write-Output '5/6 Excel report and SMTP delivery'
& $PythonExe -m forexbot.cli email-report
if ($LASTEXITCODE -ne 0) { throw 'Report/email test failed; no trade was attempted' }

if (-not $ExecuteDemoTrade) {
    Write-Output '6/6 Demo order stage skipped. Re-run with -ExecuteDemoTrade after reviewing the earlier stages.'
    exit 0
}

Write-Output '6/6 One executable demo cycle'
& $PythonExe -m forexbot.cli run-once
if ($LASTEXITCODE -ne 0) { throw 'Executable demo cycle failed' }

if ($StartContinuousTask) {
    & (Join-Path $PSScriptRoot 'install_service_task.ps1') -StartNow
    if ($LASTEXITCODE -ne 0) { throw 'Continuous task installation/start failed' }
}

Write-Output 'End-to-end demo test completed.'
