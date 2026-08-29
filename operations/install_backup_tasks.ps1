param([string]$TaskPrefix='Aurex')

$ErrorActionPreference='Stop'
$BackupScript=Join-Path $PSScriptRoot 'backup_database.ps1'
$RestoreScript=Join-Path $PSScriptRoot 'verify_restore.ps1'
$PowerShell=(Get-Command powershell.exe -ErrorAction Stop).Source

$BackupAction=New-ScheduledTaskAction -Execute $PowerShell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BackupScript`""
$BackupTrigger=New-ScheduledTaskTrigger -Daily -At '02:15'
$RestoreAction=New-ScheduledTaskAction -Execute $PowerShell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RestoreScript`""
$RestoreTrigger=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '03:00'
$Principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$Settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "$TaskPrefix SQL Backup" -Action $BackupAction -Trigger $BackupTrigger -Principal $Principal -Settings $Settings -Force | Out-Null
Register-ScheduledTask -TaskName "$TaskPrefix Restore Verification" -Action $RestoreAction -Trigger $RestoreTrigger -Principal $Principal -Settings $Settings -Force | Out-Null
Get-ScheduledTask -TaskName "$TaskPrefix SQL Backup","$TaskPrefix Restore Verification" | Select-Object TaskName,State
