USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.markets',N'asset_class') IS NULL
        ALTER TABLE app.markets ADD asset_class varchar(20) NOT NULL
            CONSTRAINT DF_markets_asset_class DEFAULT 'FX';
    IF COL_LENGTH(N'app.markets',N'calendar_code') IS NULL
        ALTER TABLE app.markets ADD calendar_code varchar(40) NOT NULL
            CONSTRAINT DF_markets_calendar DEFAULT 'FX_24X5';
    IF COL_LENGTH(N'app.markets',N'market_timezone') IS NULL
        ALTER TABLE app.markets ADD market_timezone varchar(80) NOT NULL
            CONSTRAINT DF_markets_timezone DEFAULT 'UTC';
    IF COL_LENGTH(N'app.markets',N'session_open_local') IS NULL
        ALTER TABLE app.markets ADD session_open_local time(0) NULL;
    IF COL_LENGTH(N'app.markets',N'session_close_local') IS NULL
        ALTER TABLE app.markets ADD session_close_local time(0) NULL;

    EXEC(N'UPDATE app.markets SET asset_class=''FX'',calendar_code=''FX_24X5'',market_timezone=''UTC'',
        session_open_local=NULL,session_close_local=NULL
        WHERE symbol IN (''EURUSD'',''GBPUSD'',''USDJPY'')');
    EXEC(N'UPDATE app.markets SET asset_class=''INDEX'',calendar_code=''XETRA_REGULAR'',
        market_timezone=''Europe/Berlin'',session_open_local=''09:00'',session_close_local=''17:30''
        WHERE symbol=''GERMANY40''');

    IF OBJECT_ID(N'app.market_holidays',N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_holidays
        (
            calendar_code varchar(40) NOT NULL,
            holiday_date date NOT NULL,
            holiday_name nvarchar(160) NOT NULL,
            session_close_local time(0) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_holidays_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT PK_market_holidays PRIMARY KEY(calendar_code,holiday_date)
        );
    END;

    IF COL_LENGTH(N'app.candles',N'bid_open') IS NULL ALTER TABLE app.candles ADD bid_open decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'bid_high') IS NULL ALTER TABLE app.candles ADD bid_high decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'bid_low') IS NULL ALTER TABLE app.candles ADD bid_low decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'bid_close') IS NULL ALTER TABLE app.candles ADD bid_close decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'ask_open') IS NULL ALTER TABLE app.candles ADD ask_open decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'ask_high') IS NULL ALTER TABLE app.candles ADD ask_high decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'ask_low') IS NULL ALTER TABLE app.candles ADD ask_low decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'ask_close') IS NULL ALTER TABLE app.candles ADD ask_close decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'spread_open') IS NULL ALTER TABLE app.candles ADD spread_open decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'spread_close') IS NULL ALTER TABLE app.candles ADD spread_close decimal(19,8) NULL;
    IF COL_LENGTH(N'app.candles',N'is_regular_session') IS NULL
        ALTER TABLE app.candles ADD is_regular_session bit NOT NULL
            CONSTRAINT DF_candles_regular_session DEFAULT 1;

    IF OBJECT_ID(N'app.operational_alerts',N'U') IS NULL
    BEGIN
        CREATE TABLE app.operational_alerts
        (
            operational_alert_id uniqueidentifier NOT NULL CONSTRAINT PK_operational_alerts PRIMARY KEY,
            alert_key varchar(160) NOT NULL,
            severity varchar(20) NOT NULL,
            status varchar(20) NOT NULL,
            summary nvarchar(300) NOT NULL,
            detail nvarchar(1000) NULL,
            first_seen_at_utc datetime2(3) NOT NULL,
            last_seen_at_utc datetime2(3) NOT NULL,
            last_notified_at_utc datetime2(3) NULL,
            resolved_at_utc datetime2(3) NULL,
            occurrence_count int NOT NULL CONSTRAINT DF_operational_alert_occurrences DEFAULT 1,
            CONSTRAINT UQ_operational_alert_key UNIQUE(alert_key),
            CONSTRAINT CK_operational_alert_severity CHECK(severity IN ('WARNING','CRITICAL')),
            CONSTRAINT CK_operational_alert_status CHECK(status IN ('OPEN','RESOLVED'))
        );
    END;

    IF OBJECT_ID(N'app.backup_verifications',N'U') IS NULL
    BEGIN
        CREATE TABLE app.backup_verifications
        (
            backup_verification_id uniqueidentifier NOT NULL CONSTRAINT PK_backup_verifications PRIMARY KEY,
            backup_file nvarchar(500) NOT NULL,
            backup_sha256 char(64) NULL,
            backup_size_bytes bigint NULL,
            backup_completed_at_utc datetime2(3) NULL,
            restore_verified_at_utc datetime2(3) NULL,
            status varchar(30) NOT NULL,
            detail nvarchar(1000) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_backup_verifications_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_backup_verifications_status CHECK(status IN ('BACKED_UP','RESTORE_VERIFIED','FAILED'))
        );
    END;

    IF OBJECT_ID(N'app.replay_runs',N'U') IS NULL
    BEGIN
        CREATE TABLE app.replay_runs
        (
            replay_run_id uniqueidentifier NOT NULL CONSTRAINT PK_replay_runs PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            strategy_version_id uniqueidentifier NULL,
            model_version_id uniqueidentifier NULL,
            mode varchar(30) NOT NULL,
            status varchar(30) NOT NULL,
            timeframe varchar(10) NOT NULL,
            start_time_utc datetime2(3) NULL,
            end_time_utc datetime2(3) NULL,
            initial_equity_zar decimal(19,6) NOT NULL,
            final_equity_zar decimal(19,6) NULL,
            realized_pnl_zar decimal(19,6) NULL,
            max_drawdown_pct decimal(12,6) NULL,
            candle_count int NOT NULL CONSTRAINT DF_replay_runs_candles DEFAULT 0,
            trade_count int NOT NULL CONSTRAINT DF_replay_runs_trades DEFAULT 0,
            promotable bit NOT NULL CONSTRAINT DF_replay_runs_promotable DEFAULT 0,
            non_promotable_reason varchar(100) NULL,
            input_sha256 char(64) NOT NULL,
            configuration_json nvarchar(max) NOT NULL,
            started_at_utc datetime2(3) NOT NULL CONSTRAINT DF_replay_runs_started DEFAULT SYSUTCDATETIME(),
            completed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_replay_runs_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_replay_runs_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_replay_runs_strategy FOREIGN KEY(strategy_version_id) REFERENCES app.strategy_versions(strategy_version_id),
            CONSTRAINT FK_replay_runs_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT UQ_replay_runs_input UNIQUE(tenant_id,market_id,input_sha256),
            CONSTRAINT CK_replay_runs_mode CHECK(mode IN ('VALIDATED_MODEL','TECHNICAL_DIAGNOSTIC')),
            CONSTRAINT CK_replay_runs_status CHECK(status IN ('RUNNING','COMPLETED','FAILED')),
            CONSTRAINT CK_replay_runs_timeframe CHECK(timeframe='M15'),
            CONSTRAINT CK_replay_runs_config_json CHECK(ISJSON(configuration_json)=1)
        );
        CREATE INDEX IX_replay_runs_market_time ON app.replay_runs(market_id,started_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.replay_trades',N'U') IS NULL
    BEGIN
        CREATE TABLE app.replay_trades
        (
            replay_trade_id uniqueidentifier NOT NULL CONSTRAINT PK_replay_trades PRIMARY KEY,
            replay_run_id uniqueidentifier NOT NULL,
            direction varchar(4) NOT NULL,
            size decimal(19,8) NOT NULL,
            entry_candle_id bigint NOT NULL,
            exit_candle_id bigint NULL,
            entry_price decimal(19,8) NOT NULL,
            exit_price decimal(19,8) NULL,
            stop_price decimal(19,8) NOT NULL,
            target_price decimal(19,8) NOT NULL,
            spread_cost_zar decimal(19,6) NOT NULL,
            slippage_cost_zar decimal(19,6) NOT NULL,
            funding_cost_zar decimal(19,6) NOT NULL,
            realized_pnl_zar decimal(19,6) NULL,
            exit_reason varchar(40) NULL,
            opened_at_utc datetime2(3) NOT NULL,
            closed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_replay_trades_run FOREIGN KEY(replay_run_id) REFERENCES app.replay_runs(replay_run_id),
            CONSTRAINT FK_replay_trades_entry FOREIGN KEY(entry_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT FK_replay_trades_exit FOREIGN KEY(exit_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT CK_replay_trades_direction CHECK(direction IN ('BUY','SELL'))
        );
    END;

    IF OBJECT_ID(N'app.replay_events',N'U') IS NULL
    BEGIN
        CREATE TABLE app.replay_events
        (
            replay_event_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_replay_events PRIMARY KEY,
            replay_run_id uniqueidentifier NOT NULL,
            replay_trade_id uniqueidentifier NULL,
            event_type varchar(50) NOT NULL,
            candle_id bigint NULL,
            details_json nvarchar(max) NULL,
            occurred_at_utc datetime2(3) NOT NULL,
            CONSTRAINT FK_replay_events_run FOREIGN KEY(replay_run_id) REFERENCES app.replay_runs(replay_run_id),
            CONSTRAINT FK_replay_events_trade FOREIGN KEY(replay_trade_id) REFERENCES app.replay_trades(replay_trade_id),
            CONSTRAINT FK_replay_events_candle FOREIGN KEY(candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT CK_replay_events_json CHECK(details_json IS NULL OR ISJSON(details_json)=1)
        );
    END;

    IF COL_LENGTH(N'app.model_evaluations',N'brier_score') IS NULL ALTER TABLE app.model_evaluations ADD brier_score decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'calibration_error') IS NULL ALTER TABLE app.model_evaluations ADD calibration_error decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'feature_drift_score') IS NULL ALTER TABLE app.model_evaluations ADD feature_drift_score decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'regime_coverage') IS NULL ALTER TABLE app.model_evaluations ADD regime_coverage decimal(12,8) NULL;

    IF OBJECT_ID(N'app.model_regime_results',N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_regime_results
        (
            model_regime_result_id uniqueidentifier NOT NULL CONSTRAINT PK_model_regime_results PRIMARY KEY,
            model_evaluation_id uniqueidentifier NOT NULL,
            regime_name varchar(40) NOT NULL,
            observation_count int NOT NULL,
            trade_count int NOT NULL,
            win_rate decimal(12,8) NULL,
            expectancy decimal(19,10) NULL,
            CONSTRAINT FK_model_regime_evaluation FOREIGN KEY(model_evaluation_id) REFERENCES app.model_evaluations(model_evaluation_id),
            CONSTRAINT UQ_model_regime UNIQUE(model_evaluation_id,regime_name)
        );
    END;

    IF COL_LENGTH(N'app.shadow_trades',N'entry_spread_zar') IS NULL ALTER TABLE app.shadow_trades ADD entry_spread_zar decimal(19,6) NOT NULL CONSTRAINT DF_shadow_entry_spread DEFAULT 0;
    IF COL_LENGTH(N'app.shadow_trades',N'exit_cost_zar') IS NULL ALTER TABLE app.shadow_trades ADD exit_cost_zar decimal(19,6) NOT NULL CONSTRAINT DF_shadow_exit_cost DEFAULT 0;
    IF COL_LENGTH(N'app.shadow_trades',N'holding_candles') IS NULL ALTER TABLE app.shadow_trades ADD holding_candles int NOT NULL CONSTRAINT DF_shadow_holding DEFAULT 0;
    IF COL_LENGTH(N'app.shadow_trades',N'max_holding_candles') IS NULL ALTER TABLE app.shadow_trades ADD max_holding_candles int NOT NULL CONSTRAINT DF_shadow_max_holding DEFAULT 32;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

CREATE OR ALTER VIEW app.v_market_candles
AS
    SELECT c.candle_id,c.market_id,m.symbol,m.display_name,m.asset_class,m.calendar_code,
           c.timeframe,c.open_time_utc,
           CAST((c.open_time_utc AT TIME ZONE 'UTC') AT TIME ZONE 'South Africa Standard Time' AS datetime2(3)) open_time_sast,
           c.close_time_utc,
           CAST((c.close_time_utc AT TIME ZONE 'UTC') AT TIME ZONE 'South Africa Standard Time' AS datetime2(3)) close_time_sast,
           c.[open],c.high,c.low,c.[close],c.bid_open,c.bid_high,c.bid_low,c.bid_close,
           c.ask_open,c.ask_high,c.ask_low,c.ask_close,c.spread_open,c.spread_close,
           c.is_regular_session,c.tick_count,c.source,c.completed,c.created_at_utc
    FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id;
GO

GRANT SELECT ON OBJECT::app.v_market_candles TO [ForexSaasApp];
GO
