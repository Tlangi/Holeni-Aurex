param(
    [string]$TaskName = 'Aurex Market Stream',
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$ApiRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run_market_stream.ps1'
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing virtual environment: $PythonExe" }
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ApiRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 20 `
    -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description 'Aurex IG demo Lightstreamer market-data worker.' -Force | Out-Null
Write-Output "Registered scheduled task: $TaskName"
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Started scheduled task: $TaskName"
}
