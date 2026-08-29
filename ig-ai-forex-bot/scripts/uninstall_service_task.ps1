param([string]$TaskName = 'IG AI Forex Bot')

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
Write-Output "Removed scheduled task: $TaskName"
