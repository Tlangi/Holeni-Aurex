param(
    [string]$TaskName = 'IG AI Forex Bot',
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run_bot.ps1'
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$EnvFile = Join-Path $ProjectRoot '.env'

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing virtual environment: $PythonExe" }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "Missing environment file: $EnvFile" }

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentIdentity
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentIdentity -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Runs the IG API demo forex bot.' -Force | Out-Null
Write-Output "Registered scheduled task: $TaskName"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Started scheduled task: $TaskName"
} else {
    Write-Output 'Task was not started. Run the preflight check first, then start it explicitly.'
}
