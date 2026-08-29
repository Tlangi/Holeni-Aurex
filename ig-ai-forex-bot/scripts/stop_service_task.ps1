param([string]$TaskName = 'IG AI Forex Bot')

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Write-Output "Stopped scheduled task: $TaskName"
