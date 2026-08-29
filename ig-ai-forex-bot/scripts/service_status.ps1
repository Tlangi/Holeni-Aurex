param([string]$TaskName = 'IG AI Forex Bot')

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$Info = Get-ScheduledTaskInfo -TaskName $TaskName
$Task | Select-Object TaskName, State
$Info | Select-Object LastRunTime, LastTaskResult, NextRunTime

$LogFile = Join-Path $ProjectRoot 'logs\service.log'
if (Test-Path -LiteralPath $LogFile) {
    Write-Output 'Recent log output:'
    Get-Content -LiteralPath $LogFile -Tail 30
}
