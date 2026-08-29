USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.order_intent_events', N'U') IS NULL
    BEGIN
        CREATE TABLE app.order_intent_events
        (
            order_intent_event_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_order_intent_events PRIMARY KEY,
            order_intent_id uniqueidentifier NOT NULL,
            event_type varchar(60) NOT NULL,
            from_status varchar(40) NULL,
            to_status varchar(40) NOT NULL,
            correlation_id uniqueidentifier NOT NULL,
            details_json nvarchar(max) NULL,
            occurred_at_utc datetime2(3) NOT NULL CONSTRAINT DF_order_intent_events_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_order_intent_events_intent FOREIGN KEY(order_intent_id) REFERENCES app.order_intents(order_intent_id),
            CONSTRAINT CK_order_intent_events_json CHECK(details_json IS NULL OR ISJSON(details_json)=1)
        );
        CREATE INDEX IX_order_intent_events_intent_time
            ON app.order_intent_events(order_intent_id,occurred_at_utc DESC);
    END;

    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_order_intents_status')
        ALTER TABLE app.order_intents DROP CONSTRAINT CK_order_intents_status;
    ALTER TABLE app.order_intents WITH CHECK ADD CONSTRAINT CK_order_intents_status CHECK(status IN
        ('CREATED','RISK_APPROVED','WOULD_SUBMIT','SUBMITTING','SUBMITTED','CONFIRMING','OPEN',
         'REJECTED','SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED','FAILED','CANCELLED','CLOSED'));

    IF OBJECT_ID(N'app.daily_risk_ledger', N'U') IS NULL
    BEGIN
        CREATE TABLE app.daily_risk_ledger
        (
            daily_risk_ledger_id uniqueidentifier NOT NULL CONSTRAINT PK_daily_risk_ledger PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            ledger_date_sast date NOT NULL,
            opening_equity_zar decimal(19,6) NOT NULL,
            current_equity_zar decimal(19,6) NOT NULL,
            realized_pnl_zar decimal(19,6) NOT NULL CONSTRAINT DF_daily_risk_realized DEFAULT 0,
            unrealized_pnl_zar decimal(19,6) NOT NULL CONSTRAINT DF_daily_risk_unrealized DEFAULT 0,
            reserved_risk_zar decimal(19,6) NOT NULL CONSTRAINT DF_daily_risk_reserved DEFAULT 0,
            daily_drawdown_pct decimal(12,6) NOT NULL CONSTRAINT DF_daily_risk_drawdown DEFAULT 0,
            consecutive_losses int NOT NULL CONSTRAINT DF_daily_risk_losses DEFAULT 0,
            status varchar(20) NOT NULL,
            status_reason varchar(120) NULL,
            last_reconciled_at_utc datetime2(3) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_daily_risk_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_daily_risk_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_daily_risk_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_daily_risk_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT UQ_daily_risk_account_date UNIQUE(trading_account_id,ledger_date_sast),
            CONSTRAINT CK_daily_risk_status CHECK(status IN ('CURRENT','BLOCKED','STALE')),
            CONSTRAINT CK_daily_risk_values CHECK(opening_equity_zar>=0 AND current_equity_zar>=0 AND reserved_risk_zar>=0)
        );
    END;

    IF OBJECT_ID(N'app.reconciliation_issues', N'U') IS NULL
    BEGIN
        CREATE TABLE app.reconciliation_issues
        (
            reconciliation_issue_id uniqueidentifier NOT NULL CONSTRAINT PK_reconciliation_issues PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            position_id uniqueidentifier NULL,
            issue_type varchar(60) NOT NULL,
            status varchar(20) NOT NULL,
            broker_reference_masked nvarchar(120) NULL,
            detail nvarchar(300) NOT NULL,
            first_seen_at_utc datetime2(3) NOT NULL,
            last_seen_at_utc datetime2(3) NOT NULL,
            resolved_at_utc datetime2(3) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_reconciliation_issues_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_reconciliation_issues_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_reconciliation_issues_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT FK_reconciliation_issues_position FOREIGN KEY(position_id) REFERENCES app.positions(position_id),
            CONSTRAINT CK_reconciliation_issues_status CHECK(status IN ('OPEN','INVESTIGATING','RESOLVED'))
        );
        CREATE INDEX IX_reconciliation_issues_open
            ON app.reconciliation_issues(tenant_id,status,last_seen_at_utc DESC);
    END;

    IF COL_LENGTH(N'app.positions', N'order_intent_id') IS NULL
        ALTER TABLE app.positions ADD order_intent_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.positions', N'origin') IS NULL
        ALTER TABLE app.positions ADD origin varchar(30) NOT NULL
            CONSTRAINT DF_positions_origin DEFAULT 'UNKNOWN';
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_positions_order_intent')
        ALTER TABLE app.positions ADD CONSTRAINT FK_positions_order_intent
            FOREIGN KEY(order_intent_id) REFERENCES app.order_intents(order_intent_id);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
