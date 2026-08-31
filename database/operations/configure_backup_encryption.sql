USE [master];
GO
SET NOCOUNT ON;

-- Replace the password locally. Never commit or email the real value.
:setvar MasterKeyPassword "REPLACE_WITH_LONG_OFFLINE_PASSWORD"

IF '$(MasterKeyPassword)' LIKE 'REPLACE_%'
    THROW 51000,'Replace MasterKeyPassword before configuring backup encryption.',1;

IF NOT EXISTS(SELECT 1 FROM sys.symmetric_keys WHERE name=N'##MS_DatabaseMasterKey##')
    EXEC(N'CREATE MASTER KEY ENCRYPTION BY PASSWORD=''' +
         REPLACE('$(MasterKeyPassword)','''','''''') + N'''');

IF NOT EXISTS(SELECT 1 FROM sys.certificates WHERE name=N'AurexBackupCertificate')
    CREATE CERTIFICATE AurexBackupCertificate
      WITH SUBJECT=N'Aurex encrypted off-server SQL backups',EXPIRY_DATE='2036-12-31';
GO

SELECT name,subject,expiry_date FROM sys.certificates WHERE name=N'AurexBackupCertificate';
GO

-- The certificate and private key are required to restore encrypted backups.
-- Export them to a restricted path outside this server, using a different
-- secret from the master-key password. Example (do not store the password in
-- this repository):
-- BACKUP CERTIFICATE AurexBackupCertificate
--   TO FILE='X:\secure\AurexBackupCertificate.cer'
--   WITH PRIVATE KEY(FILE='X:\secure\AurexBackupCertificate.pvk',
--                    ENCRYPTION BY PASSWORD='REPLACE_WITH_ANOTHER_OFFLINE_SECRET');
