USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.candles', N'quality_status') IS NULL
        ALTER TABLE app.candles ADD quality_status varchar(20) NOT NULL
            CONSTRAINT DF_candles_quality_status DEFAULT 'PASS';

    IF OBJECT_ID(N'app.market_data_quality_runs', N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_data_quality_runs
        (
            quality_run_id uniqueidentifier NOT NULL CONSTRAINT PK_market_data_quality_runs PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            timeframe varchar(10) NOT NULL,
            earliest_time_utc datetime2(3) NULL,
            latest_time_utc datetime2(3) NULL,
            candle_count int NOT NULL,
            duplicate_count int NOT NULL,
            missing_period_count int NOT NULL,
            invalid_ohlc_count int NOT NULL,
            nonpositive_price_count int NOT NULL,
            future_timestamp_count int NOT NULL,
            partial_candle_count int NOT NULL,
            status varchar(20) NOT NULL,
            details_json nvarchar(max) NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_quality_runs_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_quality_runs_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_quality_runs_timeframe CHECK(timeframe IN ('M5','M15')),
            CONSTRAINT CK_quality_runs_status CHECK(status IN ('PASS','WARN','FAIL')),
            CONSTRAINT CK_quality_runs_json CHECK(details_json IS NULL OR ISJSON(details_json)=1)
        );
        CREATE INDEX IX_quality_runs_market_time
            ON app.market_data_quality_runs(market_id,timeframe,evaluated_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.market_execution_states', N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_execution_states
        (
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            mode varchar(20) NOT NULL CONSTRAINT DF_market_execution_mode DEFAULT 'SHADOW',
            new_orders_enabled bit NOT NULL CONSTRAINT DF_market_execution_orders DEFAULT 0,
            reason nvarchar(300) NULL,
            changed_by_user_id uniqueidentifier NULL,
            changed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_execution_changed DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT PK_market_execution_states PRIMARY KEY(tenant_id,market_id),
            CONSTRAINT FK_market_execution_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_market_execution_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_market_execution_user FOREIGN KEY(changed_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT CK_market_execution_mode CHECK(mode IN ('SHADOW','DEMO_AUTO','PAUSED')),
            CONSTRAINT CK_market_execution_orders CHECK
                ((mode='DEMO_AUTO' AND new_orders_enabled=1) OR (mode<>'DEMO_AUTO' AND new_orders_enabled=0))
        );
    END;

    INSERT app.market_execution_states(tenant_id,market_id,mode,new_orders_enabled,reason)
    SELECT t.tenant_id,m.market_id,'SHADOW',0,N'Awaiting market-specific readiness'
    FROM app.tenants t CROSS JOIN app.markets m
    WHERE m.enabled=1 AND NOT EXISTS
      (SELECT 1 FROM app.market_execution_states s WHERE s.tenant_id=t.tenant_id AND s.market_id=m.market_id);

    IF COL_LENGTH(N'app.risk_versions', N'preferred_daily_return_pct') IS NULL
        ALTER TABLE app.risk_versions ADD preferred_daily_return_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_preferred_return DEFAULT 2.0000;
    IF COL_LENGTH(N'app.risk_versions', N'profit_protection_pct') IS NULL
        ALTER TABLE app.risk_versions ADD profit_protection_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_profit_protection DEFAULT 2.0000;
    IF COL_LENGTH(N'app.risk_versions', N'daily_profit_lock_pct') IS NULL
        ALTER TABLE app.risk_versions ADD daily_profit_lock_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_daily_profit_lock DEFAULT 10.0000;
    IF COL_LENGTH(N'app.risk_versions', N'max_portfolio_risk_pct') IS NULL
        ALTER TABLE app.risk_versions ADD max_portfolio_risk_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_portfolio_max DEFAULT 0.7500;
    IF COL_LENGTH(N'app.risk_versions', N'max_intraday_drawdown_pct') IS NULL
        ALTER TABLE app.risk_versions ADD max_intraday_drawdown_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_intraday_drawdown DEFAULT 1.5000;
    IF COL_LENGTH(N'app.risk_versions', N'profit_giveback_limit_pct') IS NULL
        ALTER TABLE app.risk_versions ADD profit_giveback_limit_pct decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_profit_giveback DEFAULT 50.0000;
    IF COL_LENGTH(N'app.risk_versions', N'max_trades_per_day') IS NULL
        ALTER TABLE app.risk_versions ADD max_trades_per_day int NOT NULL
            CONSTRAINT DF_risk_max_trades DEFAULT 6;
    IF COL_LENGTH(N'app.risk_versions', N'min_reward_risk_ratio') IS NULL
        ALTER TABLE app.risk_versions ADD min_reward_risk_ratio decimal(8,4) NOT NULL
            CONSTRAINT DF_risk_reward_ratio DEFAULT 1.5000;

    IF COL_LENGTH(N'app.daily_risk_ledger', N'peak_equity_zar') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD peak_equity_zar decimal(19,6) NULL;
    IF COL_LENGTH(N'app.daily_risk_ledger', N'intraday_drawdown_pct') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD intraday_drawdown_pct decimal(12,6) NOT NULL
            CONSTRAINT DF_daily_intraday_drawdown DEFAULT 0;
    IF COL_LENGTH(N'app.daily_risk_ledger', N'daily_return_pct') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD daily_return_pct decimal(12,6) NOT NULL
            CONSTRAINT DF_daily_return DEFAULT 0;
    IF COL_LENGTH(N'app.daily_risk_ledger', N'peak_daily_return_pct') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD peak_daily_return_pct decimal(12,6) NOT NULL
            CONSTRAINT DF_daily_peak_return DEFAULT 0;
    IF COL_LENGTH(N'app.daily_risk_ledger', N'profit_protection_state') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD profit_protection_state varchar(30) NOT NULL
            CONSTRAINT DF_daily_profit_state DEFAULT 'NORMAL';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
