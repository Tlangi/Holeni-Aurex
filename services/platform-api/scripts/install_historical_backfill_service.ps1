param([string]$ServiceName='AurexHistoricalBackfill')
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python=Join-Path $root '.venv\Scripts\python.exe'; $script=Join-Path $root 'scripts\run_historical_backfill.py'
$nssm=(Get-Command nssm.exe -ErrorAction Stop).Source
if (-not (Test-Path $python) -or -not (Test-Path $script)) { throw 'Backfill runtime files are missing.' }
if (-not (Get-Service $ServiceName -ErrorAction SilentlyContinue)) { & $nssm install $ServiceName $python $script | Out-Null }
& $nssm set $ServiceName AppDirectory $root | Out-Null
& $nssm set $ServiceName DisplayName 'Aurex Historical Backfill' | Out-Null
& $nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $nssm set $ServiceName AppStdout (Join-Path $root 'logs\historical-backfill.log') | Out-Null
& $nssm set $ServiceName AppStderr (Join-Path $root 'logs\historical-backfill-error.log') | Out-Null
& $nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
& $nssm set $ServiceName AppThrottle 10000 | Out-Null
& $nssm set $ServiceName AppExit Default Restart | Out-Null
Write-Output "Configured $ServiceName; enable with HISTORICAL_BACKFILL_ENABLED=true after validation."
