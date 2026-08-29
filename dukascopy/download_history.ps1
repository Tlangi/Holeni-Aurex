param(
    [ValidateSet('EURUSD','GBPUSD','USDJPY','GERMANY40','ALL')]
    [string]$Market = 'ALL',
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$From = '2024-01-01',
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$To = '2026-08-26',
    [ValidateRange(1, 10)]
    [int]$BatchSize = 5,
    [ValidateRange(1000, 60000)]
    [int]$BatchPauseMs = 2500,
    [ValidateRange(0, 5)]
    [int]$Retries = 3,
    [ValidateRange(1000, 120000)]
    [int]$RetryPauseMs = 15000
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$downloadRoot = Join-Path $scriptRoot 'download'
$cli = Join-Path $scriptRoot 'node_modules\.bin\dukascopy-node.cmd'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw 'Pinned dukascopy-node dependency is missing. Run npm install in C:\Projects\Forex\dukascopy.'
}
New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
$mapping = [ordered]@{
    EURUSD = 'eurusd'
    GBPUSD = 'gbpusd'
    USDJPY = 'usdjpy'
    GERMANY40 = 'deuidxeur'
}
$selected = if ($Market -eq 'ALL') { $mapping.Keys } else { @($Market) }
Push-Location $scriptRoot
try {
    foreach ($symbol in $selected) {
        $instrument = $mapping[$symbol]
        & $cli -i $instrument -from $From -to $To -t m5 -p bid -utc 0 -f csv `
            -dir $downloadRoot -bs $BatchSize -bp $BatchPauseMs -r $Retries -rp $RetryPauseMs
        if ($LASTEXITCODE -ne 0) {
            throw "Dukascopy download failed for $symbol with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}
