USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.engine_control_events', N'U') IS NULL
    BEGIN
        CREATE TABLE app.engine_control_events
        (
            engine_control_event_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_engine_control_events PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            from_mode varchar(20) NOT NULL,
            to_mode varchar(20) NOT NULL,
            from_new_orders_enabled bit NOT NULL,
            to_new_orders_enabled bit NOT NULL,
            reason nvarchar(300) NOT NULL,
            changed_by_user_id uniqueidentifier NOT NULL,
            correlation_id uniqueidentifier NOT NULL,
            occurred_at_utc datetime2(3) NOT NULL CONSTRAINT DF_engine_control_events_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_engine_control_events_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_engine_control_events_user FOREIGN KEY(changed_by_user_id) REFERENCES app.users(user_id)
        );
        CREATE INDEX IX_engine_control_events_tenant_time ON app.engine_control_events(tenant_id,occurred_at_utc DESC);
    END;

    IF COL_LENGTH(N'app.strategies', N'tenant_id') IS NULL
    BEGIN
        ALTER TABLE app.strategies ADD tenant_id uniqueidentifier NULL;
        EXEC(N'UPDATE app.strategies
               SET tenant_id=(SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc)
               WHERE tenant_id IS NULL;');
        IF EXISTS(SELECT 1 FROM app.strategies)
           AND NOT EXISTS(SELECT 1 FROM app.tenants)
            THROW 50011, 'Cannot assign existing strategies to a tenant.', 1;
        EXEC(N'ALTER TABLE app.strategies ALTER COLUMN tenant_id uniqueidentifier NOT NULL;');
        EXEC(N'ALTER TABLE app.strategies ADD CONSTRAINT FK_strategies_tenant
               FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id);');
    END;

    IF COL_LENGTH(N'app.broker_market_rules', N'deal_currency') IS NULL
        ALTER TABLE app.broker_market_rules ADD deal_currency char(3) NULL;
    IF COL_LENGTH(N'app.broker_market_rules', N'expiry') IS NULL
        ALTER TABLE app.broker_market_rules ADD expiry varchar(20) NULL;
    IF COL_LENGTH(N'app.broker_market_rules', N'force_open_allowed') IS NULL
        ALTER TABLE app.broker_market_rules ADD force_open_allowed bit NULL;
    IF COL_LENGTH(N'app.broker_market_rules', N'market_order_preference') IS NULL
        ALTER TABLE app.broker_market_rules ADD market_order_preference varchar(40) NULL;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
