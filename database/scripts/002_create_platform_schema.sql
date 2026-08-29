/*
    Phase 1 platform schema — SQL Server / T-SQL

    Run against ForexSaas using the ForexSaasApp development login. All stored
    timestamps are UTC. Money always carries an ISO 4217 currency code. Converted
    values retain their rate, source and timestamp for auditability.
*/

USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF SCHEMA_ID(N'app') IS NULL
        EXEC(N'CREATE SCHEMA [app] AUTHORIZATION [dbo];');

    IF OBJECT_ID(N'app.tenants', N'U') IS NULL
    BEGIN
        CREATE TABLE app.tenants
        (
            tenant_id uniqueidentifier NOT NULL
                CONSTRAINT PK_tenants PRIMARY KEY DEFAULT NEWSEQUENTIALID(),
            tenant_name nvarchar(160) NOT NULL,
            country_code char(2) NOT NULL
                CONSTRAINT DF_tenants_country DEFAULT 'ZA',
            reporting_currency char(3) NOT NULL
                CONSTRAINT DF_tenants_currency DEFAULT 'ZAR',
            time_zone_id nvarchar(80) NOT NULL
                CONSTRAINT DF_tenants_timezone DEFAULT 'Africa/Johannesburg',
            status varchar(20) NOT NULL CONSTRAINT DF_tenants_status DEFAULT 'active',
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_tenants_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_tenants_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT CK_tenants_country CHECK (country_code = 'ZA'),
            CONSTRAINT CK_tenants_currency CHECK (reporting_currency = 'ZAR'),
            CONSTRAINT CK_tenants_status CHECK (status IN ('active', 'suspended', 'closed'))
        );
    END;

    IF OBJECT_ID(N'app.users', N'U') IS NULL
    BEGIN
        CREATE TABLE app.users
        (
            user_id uniqueidentifier NOT NULL
                CONSTRAINT PK_users PRIMARY KEY DEFAULT NEWSEQUENTIALID(),
            tenant_id uniqueidentifier NOT NULL,
            email nvarchar(320) NOT NULL,
            display_name nvarchar(160) NOT NULL,
            password_hash nvarchar(500) NULL,
            role varchar(30) NOT NULL CONSTRAINT DF_users_role DEFAULT 'owner',
            status varchar(20) NOT NULL CONSTRAINT DF_users_status DEFAULT 'pending',
            last_login_at_utc datetime2(3) NULL,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_users_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_users_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_users_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT UQ_users_tenant_email UNIQUE (tenant_id, email),
            CONSTRAINT CK_users_role CHECK (role IN ('owner', 'administrator', 'viewer')),
            CONSTRAINT CK_users_status CHECK (status IN ('pending', 'active', 'locked', 'disabled'))
        );
    END;

    IF OBJECT_ID(N'app.broker_connections', N'U') IS NULL
    BEGIN
        CREATE TABLE app.broker_connections
        (
            broker_connection_id uniqueidentifier NOT NULL
                CONSTRAINT PK_broker_connections PRIMARY KEY DEFAULT NEWSEQUENTIALID(),
            tenant_id uniqueidentifier NOT NULL,
            broker_code varchar(30) NOT NULL,
            environment varchar(20) NOT NULL,
            external_account_id_masked nvarchar(80) NULL,
            secret_reference nvarchar(500) NOT NULL,
            status varchar(30) NOT NULL CONSTRAINT DF_broker_connections_status DEFAULT 'pending',
            account_currency char(3) NULL,
            last_authenticated_at_utc datetime2(3) NULL,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_broker_connections_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_broker_connections_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_broker_connections_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT CK_broker_connections_environment CHECK (environment = 'demo'),
            CONSTRAINT CK_broker_connections_status CHECK (status IN ('pending', 'connected', 'degraded', 'disconnected')),
            CONSTRAINT UQ_broker_connections_account UNIQUE (tenant_id, broker_code, environment, external_account_id_masked)
        );
    END;

    IF OBJECT_ID(N'app.trading_accounts', N'U') IS NULL
    BEGIN
        CREATE TABLE app.trading_accounts
        (
            trading_account_id uniqueidentifier NOT NULL
                CONSTRAINT PK_trading_accounts PRIMARY KEY DEFAULT NEWSEQUENTIALID(),
            tenant_id uniqueidentifier NOT NULL,
            broker_connection_id uniqueidentifier NOT NULL,
            account_name nvarchar(160) NOT NULL,
            external_account_id_masked nvarchar(80) NOT NULL,
            account_currency char(3) NOT NULL,
            reporting_currency char(3) NOT NULL CONSTRAINT DF_trading_accounts_reporting DEFAULT 'ZAR',
            trading_enabled bit NOT NULL CONSTRAINT DF_trading_accounts_enabled DEFAULT 0,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_trading_accounts_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_trading_accounts_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_trading_accounts_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_trading_accounts_broker FOREIGN KEY (broker_connection_id)
                REFERENCES app.broker_connections(broker_connection_id),
            CONSTRAINT CK_trading_accounts_reporting CHECK (reporting_currency = 'ZAR')
        );
    END;

    IF OBJECT_ID(N'app.fx_rates', N'U') IS NULL
    BEGIN
        CREATE TABLE app.fx_rates
        (
            fx_rate_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_fx_rates PRIMARY KEY,
            base_currency char(3) NOT NULL,
            quote_currency char(3) NOT NULL,
            rate decimal(19,8) NOT NULL,
            source varchar(40) NOT NULL,
            observed_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_fx_rates_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_fx_rates_positive CHECK (rate > 0),
            CONSTRAINT CK_fx_rates_pair CHECK (base_currency <> quote_currency),
            CONSTRAINT UQ_fx_rates_observation UNIQUE
                (base_currency, quote_currency, source, observed_at_utc)
        );
        CREATE INDEX IX_fx_rates_latest
            ON app.fx_rates(base_currency, quote_currency, observed_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.account_snapshots', N'U') IS NULL
    BEGIN
        CREATE TABLE app.account_snapshots
        (
            account_snapshot_id bigint IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_account_snapshots PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            equity decimal(19,6) NOT NULL,
            balance decimal(19,6) NOT NULL,
            available_funds decimal(19,6) NOT NULL,
            margin_used decimal(19,6) NOT NULL,
            profit_loss decimal(19,6) NOT NULL,
            source_currency char(3) NOT NULL,
            reporting_currency char(3) NOT NULL CONSTRAINT DF_account_snapshots_reporting DEFAULT 'ZAR',
            conversion_rate decimal(19,8) NOT NULL CONSTRAINT DF_account_snapshots_rate DEFAULT 1,
            conversion_source varchar(40) NOT NULL,
            conversion_observed_at_utc datetime2(3) NOT NULL,
            observed_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_account_snapshots_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_account_snapshots_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_account_snapshots_account FOREIGN KEY (trading_account_id)
                REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT CK_account_snapshots_reporting CHECK (reporting_currency = 'ZAR'),
            CONSTRAINT CK_account_snapshots_rate CHECK (conversion_rate > 0)
        );
        CREATE INDEX IX_account_snapshots_latest
            ON app.account_snapshots(trading_account_id, observed_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.positions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.positions
        (
            position_id uniqueidentifier NOT NULL
                CONSTRAINT PK_positions PRIMARY KEY DEFAULT NEWSEQUENTIALID(),
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            broker_deal_id nvarchar(120) NOT NULL,
            market_symbol varchar(30) NOT NULL,
            direction varchar(4) NOT NULL,
            size decimal(19,6) NOT NULL,
            entry_price decimal(19,8) NOT NULL,
            current_price decimal(19,8) NULL,
            stop_price decimal(19,8) NULL,
            limit_price decimal(19,8) NULL,
            unrealised_pnl decimal(19,6) NULL,
            pnl_currency char(3) NOT NULL,
            status varchar(20) NOT NULL,
            opened_at_utc datetime2(3) NOT NULL,
            closed_at_utc datetime2(3) NULL,
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_positions_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_positions_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_positions_account FOREIGN KEY (trading_account_id)
                REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT UQ_positions_broker_deal UNIQUE (trading_account_id, broker_deal_id),
            CONSTRAINT CK_positions_direction CHECK (direction IN ('BUY', 'SELL')),
            CONSTRAINT CK_positions_status CHECK (status IN ('open', 'closing', 'closed', 'reconciliation_required'))
        );
    END;

    IF OBJECT_ID(N'app.platform_components', N'U') IS NULL
    BEGIN
        CREATE TABLE app.platform_components
        (
            component_code varchar(40) NOT NULL CONSTRAINT PK_platform_components PRIMARY KEY,
            display_name nvarchar(100) NOT NULL,
            status varchar(20) NOT NULL,
            status_detail nvarchar(300) NULL,
            checked_at_utc datetime2(3) NOT NULL,
            CONSTRAINT CK_platform_components_status CHECK (status IN ('healthy', 'degraded', 'offline', 'disabled'))
        );
    END;

    IF OBJECT_ID(N'app.audit_logs', N'U') IS NULL
    BEGIN
        CREATE TABLE app.audit_logs
        (
            audit_log_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_audit_logs PRIMARY KEY,
            tenant_id uniqueidentifier NULL,
            user_id uniqueidentifier NULL,
            action_code varchar(100) NOT NULL,
            entity_type varchar(80) NULL,
            entity_id nvarchar(120) NULL,
            correlation_id uniqueidentifier NOT NULL,
            metadata_json nvarchar(max) NULL,
            occurred_at_utc datetime2(3) NOT NULL CONSTRAINT DF_audit_logs_occurred DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_audit_logs_tenant FOREIGN KEY (tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_audit_logs_user FOREIGN KEY (user_id) REFERENCES app.users(user_id),
            CONSTRAINT CK_audit_logs_json CHECK (metadata_json IS NULL OR ISJSON(metadata_json) = 1)
        );
        CREATE INDEX IX_audit_logs_tenant_time ON app.audit_logs(tenant_id, occurred_at_utc DESC);
    END;

    MERGE app.platform_components AS target
    USING
    (
        VALUES
            ('trading_engine', N'Trading engine', 'disabled', N'Execution is disabled during development'),
            ('ig_demo', N'IG demo', 'offline', N'Connection has not been tested by the platform API'),
            ('market_feed', N'Market feed', 'offline', N'Feed worker has not started'),
            ('risk_engine', N'Risk engine', 'disabled', N'Execution risk engine has not started')
    ) AS source(component_code, display_name, status, status_detail)
    ON target.component_code = source.component_code
    WHEN NOT MATCHED THEN
        INSERT(component_code, display_name, status, status_detail, checked_at_utc)
        VALUES(source.component_code, source.display_name, source.status, source.status_detail, SYSUTCDATETIME());

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
