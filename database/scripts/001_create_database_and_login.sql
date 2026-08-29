/*
    Forex SaaS SQL Server provisioning — pure T-SQL

    Run in SQL Server Management Studio as an administrator. Change the three
    values below first. No SQLCMD mode is required.

    This script does not grant sysadmin, serveradmin, db_owner, or access to
    another application's database.
*/

USE [master];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @DatabaseName sysname      = N'ForexSaas';
DECLARE @LoginName sysname         = N'ForexSaasApp';
DECLARE @AppPassword nvarchar(128) = N'REPLACE_WITH_A_LONG_UNIQUE_RANDOM_PASSWORD';

IF @DatabaseName IS NULL OR LEN(@DatabaseName) = 0
    THROW 50001, 'DatabaseName cannot be empty.', 1;

IF @LoginName IS NULL OR LEN(@LoginName) = 0
    THROW 50002, 'LoginName cannot be empty.', 1;

IF @AppPassword = N'REPLACE_WITH_A_LONG_UNIQUE_RANDOM_PASSWORD'
    THROW 50003, 'Replace AppPassword before running this script.', 1;

IF LEN(@AppPassword) < 20
    THROW 50004, 'AppPassword must contain at least 20 characters.', 1;

DECLARE @Sql nvarchar(max);

/* Create the isolated application database if necessary. */
IF DB_ID(@DatabaseName) IS NULL
BEGIN
    SET @Sql = N'CREATE DATABASE ' + QUOTENAME(@DatabaseName) + N';';
    EXEC sys.sp_executesql @Sql;
    PRINT N'Created database ' + QUOTENAME(@DatabaseName) + N'.';
END
ELSE
BEGIN
    PRINT N'Database ' + QUOTENAME(@DatabaseName) + N' already exists.';
END;

/* Create the SQL login without changing an existing login or password. */
IF NOT EXISTS
(
    SELECT 1 FROM sys.server_principals WHERE [name] = @LoginName
)
BEGIN
    SET @Sql =
        N'CREATE LOGIN ' + QUOTENAME(@LoginName) +
        N' WITH PASSWORD = ' + QUOTENAME(@AppPassword, '''') +
        N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = ' +
        QUOTENAME(@DatabaseName) + N';';

    EXEC sys.sp_executesql @Sql;
    PRINT N'Created login ' + QUOTENAME(@LoginName) + N'.';
END
ELSE
BEGIN
    PRINT N'Login ' + QUOTENAME(@LoginName) +
          N' already exists; its password was not changed.';
END;

/* USE cannot accept a variable, so database-scoped setup is parameterised SQL. */
SET @Sql =
    N'USE ' + QUOTENAME(@DatabaseName) + N';

      IF NOT EXISTS
      (
          SELECT 1
          FROM sys.database_principals
          WHERE [name] = N' + QUOTENAME(@LoginName, '''') + N'
      )
      BEGIN
          CREATE USER ' + QUOTENAME(@LoginName) +
          N' FOR LOGIN ' + QUOTENAME(@LoginName) + N';
      END;

      IF SCHEMA_ID(N''app'') IS NULL
          EXEC(N''CREATE SCHEMA [app] AUTHORIZATION [dbo];'');

      IF IS_ROLEMEMBER(N''db_datareader'', N' + QUOTENAME(@LoginName, '''') + N') <> 1
          ALTER ROLE [db_datareader] ADD MEMBER ' + QUOTENAME(@LoginName) + N';

      IF IS_ROLEMEMBER(N''db_datawriter'', N' + QUOTENAME(@LoginName, '''') + N') <> 1
          ALTER ROLE [db_datawriter] ADD MEMBER ' + QUOTENAME(@LoginName) + N';

      GRANT EXECUTE ON SCHEMA::[app] TO ' + QUOTENAME(@LoginName) + N';

      /* Development migration permissions. Use a separate identity in production. */
      GRANT CREATE TABLE TO ' + QUOTENAME(@LoginName) + N';
      GRANT CREATE VIEW TO ' + QUOTENAME(@LoginName) + N';
      GRANT CREATE PROCEDURE TO ' + QUOTENAME(@LoginName) + N';
      GRANT ALTER ON SCHEMA::[app] TO ' + QUOTENAME(@LoginName) + N';
      GRANT REFERENCES ON SCHEMA::[app] TO ' + QUOTENAME(@LoginName) + N';

      SELECT
          DB_NAME() AS [database_name],
          dp.[name] AS [database_user],
          dp.[type_desc]
      FROM sys.database_principals AS dp
      WHERE dp.[name] = N' + QUOTENAME(@LoginName, '''') + N';';

EXEC sys.sp_executesql @Sql;

PRINT N'Forex SaaS database provisioning completed successfully.';
GO
