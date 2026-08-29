param(
    [string]$SqlInstance = '',
    [string]$BackupRoot = 'C:\Projects\Forex\operations\backups'
)

$ErrorActionPreference='Stop'
$ApiRoot='C:\Projects\Forex\services\platform-api'
$PythonExe=Join-Path $ApiRoot '.venv\Scripts\python.exe'
if(-not $SqlInstance){
    Push-Location $ApiRoot
    try{$ResolvedInstance=& $PythonExe -c "from app.config import get_settings; print(get_settings().sql_server)" 2>$null}
    finally{Pop-Location}
    if($ResolvedInstance){$SqlInstance=([string]$ResolvedInstance).Trim()}
}
if(-not $SqlInstance){throw 'SQL instance could not be resolved from the platform configuration.'}
$SqlCmd=(Get-Command sqlcmd.exe -ErrorAction Stop).Source
$Script=Join-Path $PSScriptRoot 'restore_verification.sql'
$Backup=Get-ChildItem -LiteralPath $BackupRoot -Filter 'ForexSaas-*.bak' -File |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(-not $Backup){throw 'No ForexSaas backup exists to restore-test.'}

$BackupVariable = 'BackupFile="' + $Backup.FullName + '"'
& $SqlCmd -S $SqlInstance -E -C -b -i $Script -v $BackupVariable
if($LASTEXITCODE -ne 0){throw 'Disposable restore and DBCC CHECKDB verification failed.'}
& $SqlCmd -S $SqlInstance -E -C -b -d ForexSaas -Q "UPDATE app.backup_verifications SET status='RESTORE_VERIFIED',restore_verified_at_utc=SYSUTCDATETIME(),detail=N'Disposable restore and DBCC CHECKDB completed' WHERE backup_file=N'$($Backup.FullName)' AND status='BACKED_UP';"
if($LASTEXITCODE -ne 0){throw 'Restore succeeded but verification record could not be updated.'}
[pscustomobject]@{Status='RESTORE_VERIFIED';File=$Backup.FullName}
