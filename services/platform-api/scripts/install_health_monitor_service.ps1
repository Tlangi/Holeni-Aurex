param([string]$ServiceName='AurexHealthMonitor',[switch]$StartNow)

$ErrorActionPreference='Stop'
$ApiRoot=Split-Path -Parent $PSScriptRoot
$PythonExe=Join-Path $ApiRoot '.venv\Scripts\python.exe'
$Runner=Join-Path $PSScriptRoot 'run_health_monitor.py'
$LogDirectory=Join-Path $ApiRoot 'logs'
$Nssm=(Get-Command nssm.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Existing=Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if($Existing){if($Existing.Status -ne 'Stopped'){Stop-Service $ServiceName -Force}; & $Nssm remove $ServiceName confirm | Out-Null}
& $Nssm install $ServiceName $PythonExe $Runner | Out-Null
& $Nssm set $ServiceName AppDirectory $ApiRoot | Out-Null
& $Nssm set $ServiceName DisplayName 'Aurex Health Monitor' | Out-Null
& $Nssm set $ServiceName Description 'Persistent Aurex component, API and market-data health alerts.' | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 60000 | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $LogDirectory 'health-monitor-service.log') | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $LogDirectory 'health-monitor-service-error.log') | Out-Null
& $Nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $Nssm set $ServiceName AppRotateBytes 5242880 | Out-Null
Write-Output "Installed Windows service: $ServiceName"
if($StartNow){Start-Service $ServiceName; Start-Sleep -Seconds 3; Get-Service $ServiceName | Select-Object Name,Status,StartType}
