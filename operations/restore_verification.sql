USE [master];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @Target sysname=N'ForexSaasRestoreVerification';
DECLARE @Backup nvarchar(500)=N'$(BackupFile)';
DECLARE @DataPath nvarchar(500)=CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(500));
DECLARE @LogPath nvarchar(500)=CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(500));

IF @DataPath IS NULL OR @LogPath IS NULL THROW 51001,'SQL default data/log paths are unavailable.',1;
IF DB_ID(@Target) IS NOT NULL THROW 51002,'Disposable verification database already exists; refusing to overwrite it.',1;

CREATE TABLE #files
(
    LogicalName nvarchar(128),PhysicalName nvarchar(260),[Type] char(1),FileGroupName nvarchar(128) NULL,
    Size numeric(20,0),MaxSize numeric(20,0),FileID bigint,CreateLSN numeric(25,0),DropLSN numeric(25,0) NULL,
    UniqueID uniqueidentifier,ReadOnlyLSN numeric(25,0) NULL,ReadWriteLSN numeric(25,0) NULL,
    BackupSizeInBytes bigint,SourceBlockSize int,FileGroupID int,LogGroupGUID uniqueidentifier NULL,
    DifferentialBaseLSN numeric(25,0) NULL,DifferentialBaseGUID uniqueidentifier NULL,
    IsReadOnly bit,IsPresent bit,TDEThumbprint varbinary(32) NULL,SnapshotURL nvarchar(360) NULL
);

DECLARE @List nvarchar(max)=N'RESTORE FILELISTONLY FROM DISK=N'''+REPLACE(@Backup,'''','''''')+N'''';
INSERT #files EXEC(@List);
DECLARE @DataLogical sysname=(SELECT TOP(1) LogicalName FROM #files WHERE [Type]='D' ORDER BY FileID);
DECLARE @LogLogical sysname=(SELECT TOP(1) LogicalName FROM #files WHERE [Type]='L' ORDER BY FileID);
IF @DataLogical IS NULL OR @LogLogical IS NULL THROW 51003,'Backup did not contain expected data and log files.',1;

DECLARE @Restore nvarchar(max)=N'RESTORE DATABASE ['+@Target+N'] FROM DISK=N'''+REPLACE(@Backup,'''','''''')+
    N''' WITH MOVE N'''+REPLACE(@DataLogical,'''','''''')+N''' TO N'''+REPLACE(@DataPath+@Target+'.mdf','''','''''')+
    N''', MOVE N'''+REPLACE(@LogLogical,'''','''''')+N''' TO N'''+REPLACE(@LogPath+@Target+'_log.ldf','''','''''')+
    N''', RECOVERY, CHECKSUM';

BEGIN TRY
    EXEC(@Restore);
    DBCC CHECKDB([ForexSaasRestoreVerification]) WITH NO_INFOMSGS, ALL_ERRORMSGS;
    ALTER DATABASE [ForexSaasRestoreVerification] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE [ForexSaasRestoreVerification];
    SELECT 'RESTORE_VERIFIED' AS [status],@Backup AS backup_file;
END TRY
BEGIN CATCH
    IF DB_ID(@Target) IS NOT NULL
    BEGIN
        ALTER DATABASE [ForexSaasRestoreVerification] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
        DROP DATABASE [ForexSaasRestoreVerification];
    END;
    THROW;
END CATCH;
GO
