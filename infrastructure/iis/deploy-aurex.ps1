[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$ReleaseRoot = 'C:\sites\aurex\releases',
    [string]$SiteName = 'Aurex',
    [string]$AppPoolName = 'Aurex-Pool',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($SiteName -ne 'Aurex' -or $AppPoolName -ne 'Aurex-Pool') { throw 'This script is restricted to the Aurex IIS site and pool.' }

$appCmd = Join-Path $env:windir 'System32\inetsrv\appcmd.exe'
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$frontend = Join-Path $RepositoryRoot 'apps\web'
$template = Join-Path $RepositoryRoot 'infrastructure\iis\Aurex\web.config'
foreach ($required in @($appCmd, $frontend, $template)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path is missing: $required" }
}

if (-not $SkipBuild) {
    Push-Location $frontend
    try { & $npm run build; if ($LASTEXITCODE -ne 0) { throw 'Angular production build failed.' } }
    finally { Pop-Location }
}
$browserBuild = Join-Path $frontend 'dist\web\browser'
$indexSource = Join-Path $browserBuild 'index.html'
if (-not (Test-Path $indexSource)) { $indexSource = Join-Path $browserBuild 'index.csr.html' }
if (-not (Test-Path $indexSource)) { throw 'Static Angular entry document was not produced.' }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$releasePath = Join-Path $ReleaseRoot $stamp
if ($PSCmdlet.ShouldProcess($releasePath, 'Create Aurex release and update only the Aurex IIS site')) {
    New-Item -ItemType Directory -Path $releasePath -Force | Out-Null
    Copy-Item -Path (Join-Path $browserBuild '*') -Destination $releasePath -Recurse -Force
    Copy-Item -LiteralPath $indexSource -Destination (Join-Path $releasePath 'index.html') -Force
    Remove-Item -LiteralPath (Join-Path $releasePath 'index.csr.html') -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $template -Destination (Join-Path $releasePath 'web.config') -Force

    $poolExists = (& $appCmd list apppool /name:$AppPoolName) -match "APPPOOL"
    if (-not $poolExists) { & $appCmd add apppool /name:$AppPoolName /managedRuntimeVersion:"" | Out-Null }
    & $appCmd set apppool $AppPoolName /processModel.identityType:ApplicationPoolIdentity /startMode:AlwaysRunning | Out-Null

    $siteExists = (& $appCmd list site /name:$SiteName) -match "SITE"
    if (-not $siteExists) {
        & $appCmd add site /name:$SiteName /bindings:"http/*:80:holeniaurex.co.za" /physicalPath:$releasePath | Out-Null
    } else {
        & $appCmd set vdir "$SiteName/" /physicalPath:$releasePath | Out-Null
    }
    & $appCmd set app "$SiteName/" /applicationPool:$AppPoolName | Out-Null
    & $appCmd start site /site.name:$SiteName | Out-Null
    Write-Output "Aurex release activated: $releasePath"
}
