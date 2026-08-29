param(
    [string]$ServiceName = 'AurexWeb',
    [switch]$Build,
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$WebRoot = Split-Path -Parent $PSScriptRoot
$ServerEntry = Join-Path $WebRoot 'dist\web\server\server.mjs'
$LogDirectory = Join-Path $WebRoot 'logs'
$NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$Npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$Nssm = (Get-Command nssm.exe -ErrorAction Stop).Source

if ($Build) {
    & $Npm run build --prefix $WebRoot
    if ($LASTEXITCODE -ne 0) { throw 'Angular production build failed' }
}
if (-not (Test-Path -LiteralPath $ServerEntry)) {
    throw "Missing production server bundle: $ServerEntry. Run this script with -Build."
}
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$Existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Existing) {
    if ($Existing.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force }
    & $Nssm remove $ServiceName confirm | Out-Null
}

& $Nssm install $ServiceName $NodeExe $ServerEntry | Out-Null
& $Nssm set $ServiceName AppDirectory $WebRoot | Out-Null
& $Nssm set $ServiceName DisplayName 'Aurex Owner Web' | Out-Null
& $Nssm set $ServiceName Description 'Localhost-only Angular 21 production owner application.' | Out-Null
& $Nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $Nssm set $ServiceName AppEnvironmentExtra PORT=4210 HOST=127.0.0.1 AUREX_API_HOST=127.0.0.1 AUREX_API_PORT=8010 NODE_ENV=production | Out-Null
& $Nssm set $ServiceName AppExit Default Restart | Out-Null
& $Nssm set $ServiceName AppRestartDelay 30000 | Out-Null
& $Nssm set $ServiceName AppThrottle 10000 | Out-Null
& $Nssm set $ServiceName AppStdout (Join-Path $LogDirectory 'aurex-web-service.log') | Out-Null
& $Nssm set $ServiceName AppStderr (Join-Path $LogDirectory 'aurex-web-service-error.log') | Out-Null
& $Nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $Nssm set $ServiceName AppRotateBytes 5242880 | Out-Null

Write-Output "Installed Windows service: $ServiceName"
if ($StartNow) {
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3
    Get-Service -Name $ServiceName | Select-Object Name,Status,StartType
}
