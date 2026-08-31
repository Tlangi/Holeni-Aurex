param(
    [Parameter(Mandatory=$true)][string]$OffServerDirectory,
    [string]$SqlInstance = '.\SQLEXPRESS',
    [string]$Database = 'ForexSaas'
)

$ErrorActionPreference = 'Stop'
$LocalDirectory = 'C:\Projects\Forex\operations\backups\encrypted'
$ResolvedLocal = [IO.Path]::GetFullPath($LocalDirectory)
$ResolvedRemote = [IO.Path]::GetFullPath($OffServerDirectory)
if ($ResolvedRemote.StartsWith('C:\Projects\Forex',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'OffServerDirectory must not resolve inside the Aurex workspace.'
}
New-Item -ItemType Directory -Force -Path $ResolvedLocal | Out-Null
if (-not (Test-Path -LiteralPath $ResolvedRemote -PathType Container)) {
    throw 'The explicitly configured off-server destination is unavailable.'
}

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$SafeDatabaseName = $Database.Replace(']', ']]')
$FileName = "$Database-$Stamp-encrypted.bak"
$LocalFile = Join-Path $ResolvedLocal $FileName
$RemoteFile = Join-Path $ResolvedRemote $FileName
$EscapedLocal = $LocalFile.Replace("'","''")
$Query = "BACKUP DATABASE [$SafeDatabaseName] TO DISK=N'$EscapedLocal' WITH COPY_ONLY,CHECKSUM,COMPRESSION,ENCRYPTION(ALGORITHM=AES_256,SERVER CERTIFICATE=AurexBackupCertificate),STATS=10; RESTORE VERIFYONLY FROM DISK=N'$EscapedLocal' WITH CHECKSUM;"
sqlcmd -S $SqlInstance -E -b -Q $Query
Copy-Item -LiteralPath $LocalFile -Destination $RemoteFile -Force
$LocalHash = (Get-FileHash -LiteralPath $LocalFile -Algorithm SHA256).Hash
$RemoteHash = (Get-FileHash -LiteralPath $RemoteFile -Algorithm SHA256).Hash
if ($LocalHash -ne $RemoteHash) { throw 'Off-server backup checksum verification failed.' }
$EscapedRemote = $RemoteFile.Replace("'","''")
$RecordQuery = "USE [$SafeDatabaseName]; INSERT app.backup_replications(backup_replication_id,destination_code,encrypted,destination_reference,source_sha256,replicated_sha256,status,completed_at_utc) VALUES(NEWID(),'OFF_SERVER',1,N'$EscapedRemote','$LocalHash','$RemoteHash','VERIFIED',SYSUTCDATETIME());"
sqlcmd -S $SqlInstance -E -b -Q $RecordQuery
[pscustomobject]@{ Status='VERIFIED'; Encrypted=$true; File=$FileName; SHA256=$LocalHash; Destination=$ResolvedRemote }
