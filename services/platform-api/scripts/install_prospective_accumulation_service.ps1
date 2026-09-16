param([string]$ServiceName = 'AurexProspectiveAccumulation', [switch]$StartNow)
$ErrorActionPreference = 'Stop'
$ApiRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$Worker = Join-Path $PSScriptRoot 'run_prospective_accumulation_worker.py'
$LogDirectory = Join-Path $ApiRoot 'logs'
$StdoutLog = Join-Path $LogDirectory 'prospective-accumulation-service.log'
$StderrLog = Join-Path $LogDirectory 'prospective-accumulation-service-error.log'
$Nssm = (Get-Command nssm.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    if ($Existing.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force }
    & $Nssm remove $ServiceName confirm | Out-Null
}
& $Nssm install $ServiceName $PythonExe $Worker | Out-Null
& $Nssm set $ServiceName AppDirectory $ApiRoot | Out-Null
& $Nssm set $ServiceName DisplayName 'Aurex Prospective Accumulation' | Out-Null
& $Nssm set $ServiceName Description 'Append-only governed prospective opportunity evidence.' | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 120000 | Out-Null
& $Nssm set $ServiceName AppStdout $StdoutLog | Out-Null
& $Nssm set $ServiceName AppStderr $StderrLog | Out-Null
Write-Output "Installed Windows service: $ServiceName"
if ($StartNow) { Start-Service -Name $ServiceName; Start-Sleep -Seconds 3; Get-Service -Name $ServiceName }
