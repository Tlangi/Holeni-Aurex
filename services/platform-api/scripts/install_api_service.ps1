param(
    [string]$ServiceName = 'AurexPlatformAPI',
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$ApiRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'
$Runner = Join-Path $PSScriptRoot 'run_api.py'
$LogDirectory = Join-Path $ApiRoot 'logs'
$Nssm = (Get-Command nssm.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Missing virtual environment: $PythonExe" }
if (-not (Test-Path -LiteralPath (Join-Path $ApiRoot '.env'))) { throw 'Missing platform-api .env file' }
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    if ($Existing.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force }
    & $Nssm remove $ServiceName confirm | Out-Null
}

& $Nssm install $ServiceName $PythonExe $Runner | Out-Null
& $Nssm set $ServiceName AppDirectory $ApiRoot | Out-Null
& $Nssm set $ServiceName DisplayName 'Aurex Platform API' | Out-Null
& $Nssm set $ServiceName Description 'Localhost-only FastAPI service for the Aurex owner platform.' | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 30000 | Out-Null
& $Nssm set $ServiceName AppThrottle 10000 | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $LogDirectory 'platform-api-service.log') | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $LogDirectory 'platform-api-service-error.log') | Out-Null
& $Nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $Nssm set $ServiceName AppRotateBytes 5242880 | Out-Null

Write-Output "Installed Windows service: $ServiceName"
if ($StartNow) {
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3
    Get-Service -Name $ServiceName | Select-Object Name,Status,StartType
}
