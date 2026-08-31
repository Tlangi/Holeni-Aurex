USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

-- Run as a SQL administrator only after a separate deployment login has been
-- created and tested. Override this SQLCMD variable if the runtime user differs.
:setvar RuntimeUser "ForexSaasApp"

IF NOT EXISTS(SELECT 1 FROM sys.database_principals WHERE name=N'aurex_runtime')
    CREATE ROLE aurex_runtime AUTHORIZATION dbo;
GO

ALTER AUTHORIZATION ON SCHEMA::app TO dbo;
GO

IF IS_ROLEMEMBER(N'db_owner',N'$(RuntimeUser)')=1
    ALTER ROLE db_owner DROP MEMBER [$(RuntimeUser)];
IF IS_ROLEMEMBER(N'db_ddladmin',N'$(RuntimeUser)')=1
    ALTER ROLE db_ddladmin DROP MEMBER [$(RuntimeUser)];
IF IS_ROLEMEMBER(N'db_datareader',N'$(RuntimeUser)')=1
    ALTER ROLE db_datareader DROP MEMBER [$(RuntimeUser)];
IF IS_ROLEMEMBER(N'db_datawriter',N'$(RuntimeUser)')=1
    ALTER ROLE db_datawriter DROP MEMBER [$(RuntimeUser)];

ALTER ROLE aurex_runtime ADD MEMBER [$(RuntimeUser)];
GRANT SELECT,INSERT,UPDATE,DELETE ON SCHEMA::app TO aurex_runtime;
DENY ALTER,CONTROL ON SCHEMA::app TO aurex_runtime;
DENY CREATE TABLE,CREATE VIEW,CREATE PROCEDURE,CREATE FUNCTION TO aurex_runtime;
GO

SELECT USER_NAME() executed_by,
       IS_ROLEMEMBER(N'aurex_runtime',N'$(RuntimeUser)') runtime_member,
       IS_ROLEMEMBER(N'db_owner',N'$(RuntimeUser)') db_owner_member,
       IS_ROLEMEMBER(N'db_ddladmin',N'$(RuntimeUser)') ddladmin_member;
GO
