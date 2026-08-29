# SQL Server Express connection handoff

## Current finding

The `MSSQL$SQLEXPRESS` Windows service is running. SQL Server registry settings show
shared memory and TCP enabled, with TCP port `1433` configured. However, the running
instance is not listening on port `1433`, and local ODBC attempts fail with SQLSTATE
`08001` before authentication.

This normally means the SQL protocol/port configuration has not been activated in
the running service. SQL Browser is disabled, so named-instance TCP discovery is
also unavailable.

## Safe administrator action

Because this server hosts other applications, first identify all applications using
the `SQLEXPRESS` instance and schedule a short maintenance window. Then:

1. Open SQL Server Configuration Manager.
2. Confirm TCP/IP is enabled for `SQLEXPRESS`.
3. Confirm `IPAll` uses the intended fixed TCP port (`1433`) and has no conflicting
   dynamic port.
4. Restart only **SQL Server (SQLEXPRESS)** during the approved window.
5. Confirm a listener exists:

   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 1433
   ```

6. Test locally without printing credentials:

   ```powershell
   Set-Location C:\Projects\Forex\services\platform-api
   .\.venv\Scripts\python.exe -c "from app.config import get_settings; from app.database import check_database; print(check_database(get_settings()))"
   ```

7. Apply the Phase 1 schema:

   ```powershell
   .\.venv\Scripts\python.exe scripts\apply_migration.py ..\..\database\scripts\002_create_platform_schema.sql
   ```

### SSMS fallback

If command-line ODBC still fails before authentication, open
`database/scripts/002_create_platform_schema.sql` in SSMS, connect using the same
administrator context used to create `ForexSaas`, select the `ForexSaas` database,
and execute the script there. Keep `ForexSaasApp` as the runtime login; do not make
it `db_owner` to work around a client TLS or security-package failure.

Verify the development login's scoped DDL permissions in SSMS:

```sql
USE [ForexSaas];
GO

EXECUTE AS USER = N'ForexSaasApp';

SELECT
    HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'CREATE TABLE') AS can_create_table,
    HAS_PERMS_BY_NAME(N'app', N'SCHEMA', N'ALTER') AS can_alter_app_schema,
    IS_ROLEMEMBER(N'db_datareader') AS is_datareader,
    IS_ROLEMEMBER(N'db_datawriter') AS is_datawriter;

REVERT;
GO
```

The expected result is `1` for all four checks. These grants are enough for the
current migration runner and application without granting ownership of the database.

Do not change the instance name, global firewall, credentials, or databases belonging
to other applications as part of this work. If port `1433` is already reserved by a
different SQL instance, assign a documented non-conflicting fixed port to SQLEXPRESS
and set `SQL_SERVER=localhost,<port>` in the platform `.env`.

## Encryption

Keep `SQL_ENCRYPT=true` where the SQL instance supports TLS. For an entirely local
development connection, `SQL_ENCRYPT=false` may be used temporarily only if TLS is
the confirmed blocker. Remote and production database traffic must be encrypted.
