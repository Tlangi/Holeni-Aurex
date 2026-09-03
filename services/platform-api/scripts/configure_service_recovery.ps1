param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$services = @('AurexPlatformAPI','AurexWeb','AurexMarketStream','AurexTradingWorker','AurexHealthMonitor')

if (-not $Apply) {
    Write-Output 'Dry run only. Re-run elevated with -Apply to configure the five named Aurex services.'
    foreach ($name in $services) {
        [pscustomobject]@{ Service=$name; ResetSeconds=86400; Actions='restart/5000,restart/15000,restart/60000' }
    }
    exit 0
}

foreach ($name in $services) {
    if (-not (Get-Service -Name $name -ErrorAction SilentlyContinue)) {
        throw "Required service is not installed: $name"
    }
    & sc.exe failure $name reset= 86400 actions= restart/5000/restart/15000/restart/60000
    if ($LASTEXITCODE -ne 0) { throw "Recovery configuration failed: $name" }
    & sc.exe failureflag $name 1
    if ($LASTEXITCODE -ne 0) { throw "Failure flag configuration failed: $name" }
}
Write-Output 'Aurex service recovery configuration applied. No service was stopped or restarted.'
