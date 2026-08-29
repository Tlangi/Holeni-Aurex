param(
    [string]$SqlInstance = '',
    [string]$Database = 'ForexSaas',
    [string]$BackupRoot = 'C:\Projects\Forex\operations\backups'
)

$ErrorActionPreference = 'Stop'
$Workspace = [IO.Path]::GetFullPath('C:\Projects\Forex')
$ResolvedRoot = [IO.Path]::GetFullPath($BackupRoot)
if (-not $ResolvedRoot.StartsWith($Workspace, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackupRoot must remain inside C:\Projects\Forex.'
}
if ($Database -ne 'ForexSaas') { throw 'This task is restricted to the ForexSaas database.' }
$ApiRoot = Join-Path $Workspace 'services\platform-api'
$PythonExe = Join-Path $ApiRoot '.venv\Scripts\python.exe'
if (-not $SqlInstance) {
    Push-Location $ApiRoot
    try {
        $ResolvedInstance = & $PythonExe -c "from app.config import get_settings; print(get_settings().sql_server)" 2>$null
    }
    finally { Pop-Location }
    if ($ResolvedInstance) { $SqlInstance = ([string]$ResolvedInstance).Trim() }
}
if (-not $SqlInstance) { throw 'SQL instance could not be resolved from the platform configuration.' }
$SqlCmd = (Get-Command sqlcmd.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force -Path $ResolvedRoot | Out-Null
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$BackupFile = Join-Path $ResolvedRoot "ForexSaas-$Stamp.bak"

& $SqlCmd -S $SqlInstance -E -C -b -Q "BACKUP DATABASE [ForexSaas] TO DISK=N'$BackupFile' WITH COPY_ONLY, INIT, CHECKSUM, STATS=10; RESTORE VERIFYONLY FROM DISK=N'$BackupFile' WITH CHECKSUM;"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $BackupFile)) { throw 'SQL backup or VERIFYONLY failed.' }

$File = Get-Item -LiteralPath $BackupFile
$Hash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
$VerificationId = [guid]::NewGuid().ToString()
& $SqlCmd -S $SqlInstance -E -C -b -d ForexSaas -Q "INSERT app.backup_verifications(backup_verification_id,backup_file,backup_sha256,backup_size_bytes,backup_completed_at_utc,status,detail) VALUES('$VerificationId',N'$BackupFile','$Hash',$($File.Length),SYSUTCDATETIME(),'BACKED_UP',N'BACKUP DATABASE and RESTORE VERIFYONLY completed');"
if ($LASTEXITCODE -ne 0) { throw 'Backup succeeded but verification record could not be persisted.' }

Get-ChildItem -LiteralPath $ResolvedRoot -Filter 'ForexSaas-*.bak' -File |
    Where-Object LastWriteTimeUtc -lt (Get-Date).ToUniversalTime().AddDays(-14) |
    Remove-Item -Force

[pscustomobject]@{ Status='BACKED_UP'; File=$BackupFile; SizeBytes=$File.Length; Sha256=$Hash }
