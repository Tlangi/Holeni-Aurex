[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$ReleasePath,
    [string]$SiteName = 'Aurex'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($SiteName -ne 'Aurex') { throw 'This rollback script is restricted to the Aurex IIS site.' }
$resolved = (Resolve-Path -LiteralPath $ReleasePath).Path
$allowedRoot = [IO.Path]::GetFullPath('C:\sites\aurex\releases')
if (-not $resolved.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'ReleasePath must be a versioned Aurex release.'
}
if (-not (Test-Path (Join-Path $resolved 'index.html')) -or -not (Test-Path (Join-Path $resolved 'web.config'))) {
    throw 'The requested release is incomplete.'
}
$appCmd = Join-Path $env:windir 'System32\inetsrv\appcmd.exe'
if ($PSCmdlet.ShouldProcess($resolved, 'Point only the Aurex IIS site to this release')) {
    & $appCmd set vdir "$SiteName/" /physicalPath:$resolved | Out-Null
    & $appCmd recycle apppool /apppool.name:'Aurex-Pool' | Out-Null
    Write-Output "Aurex rolled back to: $resolved"
}
