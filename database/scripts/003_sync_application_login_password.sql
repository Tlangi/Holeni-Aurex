/*
    Synchronize the ForexSaasApp SQL login with services/platform-api/.env.

    Run in SSMS as a SQL Server administrator. Replace the placeholder with the
    exact SQL_PASSWORD value from the local .env, execute, then close this query
    without saving the real password to disk or source control.
*/

USE [master];
GO

DECLARE @NewPassword nvarchar(128) = N'REPLACE_WITH_THE_EXACT_ENV_SQL_PASSWORD';

IF @NewPassword = N'REPLACE_WITH_THE_EXACT_ENV_SQL_PASSWORD'
    THROW 50010, 'Replace NewPassword before running this script.', 1;

DECLARE @Sql nvarchar(max) =
    N'ALTER LOGIN [ForexSaasApp] WITH PASSWORD = ' +
    QUOTENAME(@NewPassword, '''') +
    N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF; ALTER LOGIN [ForexSaasApp] ENABLE;';

EXEC sys.sp_executesql @Sql;

PRINT N'ForexSaasApp password synchronized and login enabled.';
GO
