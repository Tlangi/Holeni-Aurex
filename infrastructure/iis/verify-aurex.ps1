[CmdletBinding()]
param([string]$HostName = 'holeniaurex.co.za')
$ErrorActionPreference = 'Stop'
$results = [Collections.Generic.List[object]]::new()
function Add-Check($Name, $Passed, $Evidence) {
    $results.Add([pscustomobject]@{ Check=$Name; Passed=[bool]$Passed; Evidence=$Evidence })
}
$api = Get-NetTCPConnection -State Listen -LocalPort 8010 -ErrorAction SilentlyContinue
Add-Check 'FastAPI loopback-only' ($api -and -not ($api.LocalAddress | Where-Object { $_ -notin '127.0.0.1','::1' })) (($api.LocalAddress | Sort-Object -Unique) -join ',')
$web = Get-NetTCPConnection -State Listen -LocalPort 4210 -ErrorAction SilentlyContinue
Add-Check 'Legacy web loopback-only' ($web -and -not ($web.LocalAddress | Where-Object { $_ -notin '127.0.0.1','::1' })) (($web.LocalAddress | Sort-Object -Unique) -join ',')
try { $local = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1/health/live' -Headers @{Host=$HostName} -MaximumRedirection 0; Add-Check 'HTTP redirects' ($local.StatusCode -in 301,308) $local.StatusCode }
catch { $code = [int]$_.Exception.Response.StatusCode; Add-Check 'HTTP redirects' ($code -in 301,308) $code }
try { $dns = Resolve-DnsName $HostName -Type A -Server '1.1.1.1' -ErrorAction Stop; Add-Check 'Public A record' ($null -ne $dns.IPAddress) (($dns.IPAddress) -join ',') }
catch { Add-Check 'Public A record' $false 'not resolved' }
$results | Format-Table -AutoSize
if ($results.Passed -contains $false) { exit 1 }
