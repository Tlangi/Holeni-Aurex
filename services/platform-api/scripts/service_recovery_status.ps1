$ErrorActionPreference = 'Continue'
$services = @(
    'AurexPlatformAPI', 'AurexWeb', 'AurexMarketStream',
    'AurexTradingWorker', 'AurexHealthMonitor'
)

foreach ($serviceName in $services) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $service) {
        [pscustomobject]@{ Service = $serviceName; Status = 'NOT_INSTALLED';
            StartupType = $null; Recovery = 'NOT_AVAILABLE'; AdminCommand = $null }
        continue
    }
    $qc = (& sc.exe qc $serviceName 2>&1) -join "`n"
    $failure = (& sc.exe qfailure $serviceName 2>&1) -join "`n"
    $denied = ($qc + $failure) -match 'Access is denied|OpenService FAILED 5'
    [pscustomobject]@{
        Service = $serviceName
        Status = [string]$service.Status
        StartupType = [string]$service.StartType
        Recovery = if ($denied) { 'ADMIN_REQUIRED' } else { $failure.Trim() }
        AdminCommand = if ($denied) {
            "Run elevated: sc.exe qc $serviceName; sc.exe qfailure $serviceName"
        } else { $null }
    }
}
