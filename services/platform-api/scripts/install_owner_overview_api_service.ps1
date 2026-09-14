param([switch]$StartNow)

$ErrorActionPreference = 'Stop'
$ServiceName = 'AurexOwnerOverviewAPI'
$ApiRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$Runner = Join-Path $PSScriptRoot 'run_owner_overview_api.py'
$LogDirectory = Join-Path $ApiRoot 'logs'
$Nssm = (Get-Command nssm.exe -ErrorAction Stop).Source

foreach ($required in @($PythonExe, $Runner, (Join-Path $ApiRoot '.env'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing owner API prerequisite: $required" }
}
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    throw "$ServiceName already exists. Refusing to replace or restart it automatically."
}
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
& $Nssm install $ServiceName $PythonExe $Runner | Out-Null
& $Nssm set $ServiceName AppDirectory $ApiRoot | Out-Null
& $Nssm set $ServiceName DisplayName 'Aurex Owner Overview API' | Out-Null
& $Nssm set $ServiceName Description 'Localhost-only, GET-only owner summaries; no trading scheduler.' | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 30000 | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $LogDirectory 'owner-overview-api.log') | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $LogDirectory 'owner-overview-api-error.log') | Out-Null
Write-Output "Installed Windows service: $ServiceName"
if ($StartNow) {
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 2
    $service = Get-Service -Name $ServiceName
    if ($service.Status -ne 'Running') { throw "$ServiceName failed to start" }
    Write-Output "$ServiceName running on localhost port 8011"
}
