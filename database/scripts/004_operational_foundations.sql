USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.auth_sessions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.auth_sessions
        (
            session_id uniqueidentifier NOT NULL CONSTRAINT PK_auth_sessions PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            user_id uniqueidentifier NOT NULL,
            token_hash binary(32) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_auth_sessions_created DEFAULT SYSUTCDATETIME(),
            expires_at_utc datetime2(3) NOT NULL,
            last_seen_at_utc datetime2(3) NOT NULL CONSTRAINT DF_auth_sessions_seen DEFAULT SYSUTCDATETIME(),
            revoked_at_utc datetime2(3) NULL,
            user_agent_hash binary(32) NULL,
            row_version rowversion NOT NULL,
            CONSTRAINT FK_auth_sessions_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_auth_sessions_user FOREIGN KEY (user_id) REFERENCES app.users(user_id),
            CONSTRAINT UQ_auth_sessions_token UNIQUE (token_hash)
        );
        CREATE INDEX IX_auth_sessions_active
            ON app.auth_sessions(user_id, expires_at_utc)
            WHERE revoked_at_utc IS NULL;
    END;

    IF OBJECT_ID(N'app.sync_runs', N'U') IS NULL
    BEGIN
        CREATE TABLE app.sync_runs
        (
            sync_run_id uniqueidentifier NOT NULL CONSTRAINT PK_sync_runs PRIMARY KEY,
            tenant_id uniqueidentifier NULL,
            broker_connection_id uniqueidentifier NULL,
            trading_account_id uniqueidentifier NULL,
            correlation_id uniqueidentifier NOT NULL,
            worker varchar(60) NOT NULL,
            status varchar(30) NOT NULL,
            attempt smallint NOT NULL CONSTRAINT DF_sync_runs_attempt DEFAULT 1,
            positions_seen int NOT NULL CONSTRAINT DF_sync_runs_positions DEFAULT 0,
            snapshot_created bit NOT NULL CONSTRAINT DF_sync_runs_snapshot DEFAULT 0,
            error_code varchar(80) NULL,
            started_at_utc datetime2(3) NOT NULL,
            completed_at_utc datetime2(3) NULL,
            duration_ms int NULL,
            CONSTRAINT FK_sync_runs_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_sync_runs_broker FOREIGN KEY (broker_connection_id)
                REFERENCES app.broker_connections(broker_connection_id),
            CONSTRAINT FK_sync_runs_account FOREIGN KEY (trading_account_id)
                REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT CK_sync_runs_status CHECK
                (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED_LOCKED'))
        );
        CREATE INDEX IX_sync_runs_recent ON app.sync_runs(started_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.position_events', N'U') IS NULL
    BEGIN
        CREATE TABLE app.position_events
        (
            position_event_id bigint IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_position_events PRIMARY KEY,
            position_id uniqueidentifier NOT NULL,
            event_type varchar(50) NOT NULL,
            from_status varchar(30) NULL,
            to_status varchar(30) NOT NULL,
            broker_observed bit NOT NULL,
            correlation_id uniqueidentifier NOT NULL,
            details_json nvarchar(max) NULL,
            occurred_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_position_events_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_position_events_position FOREIGN KEY (position_id)
                REFERENCES app.positions(position_id),
            CONSTRAINT CK_position_events_json CHECK
                (details_json IS NULL OR ISJSON(details_json) = 1)
        );
        CREATE INDEX IX_position_events_position_time
            ON app.position_events(position_id, occurred_at_utc DESC);
    END;

    IF COL_LENGTH(N'app.account_snapshots', N'snapshot_fingerprint') IS NULL
    BEGIN
        ALTER TABLE app.account_snapshots ADD snapshot_fingerprint char(64) NULL;
        EXEC(N'CREATE UNIQUE INDEX UX_account_snapshots_fingerprint
            ON app.account_snapshots(trading_account_id, snapshot_fingerprint)
            WHERE snapshot_fingerprint IS NOT NULL;');
    END;

    IF COL_LENGTH(N'app.positions', N'broker_missing_at_utc') IS NULL
        ALTER TABLE app.positions ADD broker_missing_at_utc datetime2(3) NULL;

    IF COL_LENGTH(N'app.positions', N'reconciliation_attempts') IS NULL
        ALTER TABLE app.positions ADD reconciliation_attempts int NOT NULL
            CONSTRAINT DF_positions_reconciliation_attempts DEFAULT 0;

    IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name=N'CK_positions_status')
        ALTER TABLE app.positions DROP CONSTRAINT CK_positions_status;

    UPDATE app.positions SET status=UPPER(status);

    ALTER TABLE app.positions WITH CHECK ADD CONSTRAINT CK_positions_status CHECK
        (status IN ('OPEN', 'BROKER_MISSING', 'RECONCILING', 'CLOSING', 'CLOSED',
                    'RESOLVED', 'RECONCILIATION_REQUIRED'));

    IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name=N'CK_platform_components_status')
        ALTER TABLE app.platform_components DROP CONSTRAINT CK_platform_components_status;

    UPDATE app.platform_components
    SET status = CASE UPPER(status)
        WHEN 'HEALTHY' THEN 'CURRENT'
        WHEN 'DEGRADED' THEN 'DEGRADED'
        WHEN 'OFFLINE' THEN 'ERROR'
        WHEN 'DISABLED' THEN 'DISABLED'
        ELSE 'UNKNOWN' END;

    ALTER TABLE app.platform_components WITH CHECK ADD CONSTRAINT CK_platform_components_status CHECK
        (status IN ('CURRENT', 'SYNCING', 'STALE', 'DEGRADED', 'ERROR', 'DISABLED', 'UNKNOWN'));

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
