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

    IF OBJECT_ID(N'app.markets', N'U') IS NULL
    BEGIN
        CREATE TABLE app.markets
        (
            market_id uniqueidentifier NOT NULL CONSTRAINT PK_markets PRIMARY KEY,
            symbol varchar(12) NOT NULL,
            display_name nvarchar(80) NOT NULL,
            ig_epic varchar(100) NOT NULL,
            base_currency char(3) NOT NULL,
            quote_currency char(3) NOT NULL,
            price_digits tinyint NOT NULL,
            enabled bit NOT NULL CONSTRAINT DF_markets_enabled DEFAULT 1,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_markets_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT UQ_markets_symbol UNIQUE(symbol),
            CONSTRAINT UQ_markets_epic UNIQUE(ig_epic)
        );
    END;

    IF OBJECT_ID(N'app.candles', N'U') IS NULL
    BEGIN
        CREATE TABLE app.candles
        (
            candle_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_candles PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            timeframe varchar(10) NOT NULL,
            open_time_utc datetime2(3) NOT NULL,
            close_time_utc datetime2(3) NOT NULL,
            [open] decimal(19,8) NOT NULL,
            high decimal(19,8) NOT NULL,
            low decimal(19,8) NOT NULL,
            [close] decimal(19,8) NOT NULL,
            tick_count bigint NOT NULL CONSTRAINT DF_candles_ticks DEFAULT 0,
            source varchar(30) NOT NULL,
            completed bit NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_candles_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_candles_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_candles_market_time UNIQUE(market_id, timeframe, open_time_utc),
            CONSTRAINT CK_candles_timeframe CHECK(timeframe IN ('M5','M15')),
            CONSTRAINT CK_candles_prices CHECK(high >= low AND high >= [open] AND high >= [close]
                AND low <= [open] AND low <= [close])
        );
        CREATE INDEX IX_candles_strategy_window
            ON app.candles(market_id, timeframe, completed, open_time_utc DESC);
    END;

    IF OBJECT_ID(N'app.strategies', N'U') IS NULL
    BEGIN
        CREATE TABLE app.strategies
        (
            strategy_id uniqueidentifier NOT NULL CONSTRAINT PK_strategies PRIMARY KEY,
            strategy_name nvarchar(120) NOT NULL,
            environment varchar(20) NOT NULL,
            status varchar(20) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_strategies_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT UQ_strategies_name UNIQUE(strategy_name),
            CONSTRAINT CK_strategies_environment CHECK(environment='DEMO'),
            CONSTRAINT CK_strategies_status CHECK(status IN ('ACTIVE','PAUSED','RETIRED'))
        );
    END;

    IF OBJECT_ID(N'app.strategy_versions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.strategy_versions
        (
            strategy_version_id uniqueidentifier NOT NULL CONSTRAINT PK_strategy_versions PRIMARY KEY,
            strategy_id uniqueidentifier NOT NULL,
            version varchar(30) NOT NULL,
            timeframe varchar(10) NOT NULL,
            buy_threshold decimal(8,6) NOT NULL,
            sell_threshold decimal(8,6) NOT NULL,
            features_version varchar(30) NOT NULL,
            released_at_utc datetime2(3) NOT NULL CONSTRAINT DF_strategy_versions_released DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_strategy_versions_strategy FOREIGN KEY(strategy_id) REFERENCES app.strategies(strategy_id),
            CONSTRAINT UQ_strategy_versions_version UNIQUE(strategy_id,version),
            CONSTRAINT CK_strategy_versions_thresholds CHECK
                (sell_threshold > 0 AND sell_threshold < buy_threshold AND buy_threshold < 1)
        );
    END;

    IF OBJECT_ID(N'app.model_versions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_versions
        (
            model_version_id uniqueidentifier NOT NULL CONSTRAINT PK_model_versions PRIMARY KEY,
            strategy_version_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            model_name nvarchar(120) NOT NULL,
            version varchar(30) NOT NULL,
            artifact_path nvarchar(500) NOT NULL,
            artifact_sha256 char(64) NOT NULL,
            validation_auc decimal(8,6) NULL,
            training_rows int NULL,
            status varchar(20) NOT NULL,
            registered_at_utc datetime2(3) NOT NULL CONSTRAINT DF_models_registered DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_models_strategy_version FOREIGN KEY(strategy_version_id)
                REFERENCES app.strategy_versions(strategy_version_id),
            CONSTRAINT FK_models_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_models_version UNIQUE(strategy_version_id,market_id,version),
            CONSTRAINT CK_models_status CHECK(status IN ('REGISTERED','VALIDATED','REJECTED','RETIRED'))
        );
    END;

    IF OBJECT_ID(N'app.signals', N'U') IS NULL
    BEGIN
        CREATE TABLE app.signals
        (
            signal_id uniqueidentifier NOT NULL CONSTRAINT PK_signals PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            strategy_version_id uniqueidentifier NOT NULL,
            model_version_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            candle_id bigint NOT NULL,
            direction varchar(4) NOT NULL,
            confidence decimal(8,6) NOT NULL,
            atr decimal(19,8) NOT NULL,
            deterministic_key char(64) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_signals_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_signals_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_signals_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT FK_signals_strategy FOREIGN KEY(strategy_version_id) REFERENCES app.strategy_versions(strategy_version_id),
            CONSTRAINT FK_signals_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_signals_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_signals_candle FOREIGN KEY(candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT UQ_signals_deterministic UNIQUE(deterministic_key),
            CONSTRAINT CK_signals_direction CHECK(direction IN ('BUY','SELL','HOLD')),
            CONSTRAINT CK_signals_confidence CHECK(confidence >= 0 AND confidence <= 1)
        );
    END;

    IF OBJECT_ID(N'app.risk_versions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.risk_versions
        (
            risk_version_id uniqueidentifier NOT NULL CONSTRAINT PK_risk_versions PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            version int NOT NULL,
            risk_per_trade_pct decimal(8,4) NOT NULL,
            daily_loss_limit_pct decimal(8,4) NOT NULL,
            max_open_positions int NOT NULL,
            max_positions_per_market int NOT NULL,
            max_consecutive_losses int NOT NULL,
            require_stop bit NOT NULL,
            require_take_profit bit NOT NULL,
            block_stale_data bit NOT NULL,
            block_unresolved_reconciliation bit NOT NULL,
            active bit NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_risk_versions_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_risk_versions_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT UQ_risk_versions_version UNIQUE(tenant_id,version),
            CONSTRAINT CK_risk_versions_limits CHECK
                (risk_per_trade_pct > 0 AND risk_per_trade_pct <= 1
                 AND daily_loss_limit_pct > 0 AND daily_loss_limit_pct <= 10
                 AND max_open_positions > 0 AND max_positions_per_market > 0
                 AND max_consecutive_losses > 0)
        );
        CREATE UNIQUE INDEX UX_risk_versions_active
            ON app.risk_versions(tenant_id) WHERE active=1;
    END;

    IF OBJECT_ID(N'app.risk_decisions', N'U') IS NULL
    BEGIN
        CREATE TABLE app.risk_decisions
        (
            risk_decision_id uniqueidentifier NOT NULL CONSTRAINT PK_risk_decisions PRIMARY KEY,
            signal_id uniqueidentifier NOT NULL,
            risk_version_id uniqueidentifier NOT NULL,
            decision varchar(20) NOT NULL,
            reason_code varchar(80) NOT NULL,
            equity_zar decimal(19,6) NOT NULL,
            planned_risk_zar decimal(19,6) NULL,
            calculated_size decimal(19,8) NULL,
            stop_level decimal(19,8) NULL,
            take_profit_level decimal(19,8) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_risk_decisions_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_risk_decisions_signal FOREIGN KEY(signal_id) REFERENCES app.signals(signal_id),
            CONSTRAINT FK_risk_decisions_version FOREIGN KEY(risk_version_id) REFERENCES app.risk_versions(risk_version_id),
            CONSTRAINT UQ_risk_decisions_signal UNIQUE(signal_id),
            CONSTRAINT CK_risk_decisions_decision CHECK(decision IN ('APPROVED','REJECTED','WOULD_APPROVE'))
        );
    END;

    IF OBJECT_ID(N'app.order_intents', N'U') IS NULL
    BEGIN
        CREATE TABLE app.order_intents
        (
            order_intent_id uniqueidentifier NOT NULL CONSTRAINT PK_order_intents PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            trading_account_id uniqueidentifier NOT NULL,
            signal_id uniqueidentifier NOT NULL,
            risk_decision_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            direction varchar(4) NOT NULL,
            calculated_size decimal(19,8) NOT NULL,
            stop_level decimal(19,8) NOT NULL,
            take_profit_level decimal(19,8) NOT NULL,
            risk_amount_zar decimal(19,6) NOT NULL,
            status varchar(40) NOT NULL,
            deterministic_key char(64) NOT NULL,
            client_reference varchar(80) NOT NULL,
            broker_deal_reference nvarchar(120) NULL,
            failure_code varchar(100) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_order_intents_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_order_intents_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_order_intents_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_order_intents_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
            CONSTRAINT FK_order_intents_signal FOREIGN KEY(signal_id) REFERENCES app.signals(signal_id),
            CONSTRAINT FK_order_intents_risk FOREIGN KEY(risk_decision_id) REFERENCES app.risk_decisions(risk_decision_id),
            CONSTRAINT FK_order_intents_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_order_intents_deterministic UNIQUE(deterministic_key),
            CONSTRAINT UQ_order_intents_reference UNIQUE(client_reference),
            CONSTRAINT CK_order_intents_status CHECK(status IN
                ('CREATED','RISK_APPROVED','WOULD_SUBMIT','SUBMITTING','SUBMITTED',
                 'CONFIRMING','OPEN','REJECTED','SUBMISSION_UNKNOWN',
                 'RECONCILIATION_REQUIRED','FAILED'))
        );
    END;

    IF OBJECT_ID(N'app.engine_controls', N'U') IS NULL
    BEGIN
        CREATE TABLE app.engine_controls
        (
            tenant_id uniqueidentifier NOT NULL CONSTRAINT PK_engine_controls PRIMARY KEY,
            mode varchar(20) NOT NULL,
            new_orders_enabled bit NOT NULL,
            pause_reason nvarchar(300) NULL,
            changed_by_user_id uniqueidentifier NULL,
            changed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_engine_controls_changed DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_engine_controls_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_engine_controls_user FOREIGN KEY(changed_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT CK_engine_controls_mode CHECK(mode IN ('READ_ONLY','SHADOW','DEMO_AUTO','PAUSED')),
            CONSTRAINT CK_engine_controls_orders CHECK
                ((mode='DEMO_AUTO' AND new_orders_enabled=1) OR
                 (mode<>'DEMO_AUTO' AND new_orders_enabled=0))
        );
    END;

    MERGE app.markets AS target
    USING (VALUES
        ('EURUSD',N'EUR/USD','CS.D.EURUSD.CFD.IP','EUR','USD',5),
        ('GBPUSD',N'GBP/USD','CS.D.GBPUSD.CFD.IP','GBP','USD',5),
        ('USDJPY',N'USD/JPY','CS.D.USDJPY.CFD.IP','USD','JPY',3)
    ) AS source(symbol,display_name,ig_epic,base_currency,quote_currency,price_digits)
    ON target.symbol=source.symbol
    WHEN NOT MATCHED THEN INSERT
        (market_id,symbol,display_name,ig_epic,base_currency,quote_currency,price_digits)
        VALUES(NEWID(),source.symbol,source.display_name,source.ig_epic,
               source.base_currency,source.quote_currency,source.price_digits);

    DECLARE @tenant_id uniqueidentifier=(SELECT TOP(1) tenant_id FROM app.tenants ORDER BY created_at_utc);
    IF @tenant_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.risk_versions WHERE tenant_id=@tenant_id)
        INSERT INTO app.risk_versions
            (risk_version_id,tenant_id,version,risk_per_trade_pct,daily_loss_limit_pct,
             max_open_positions,max_positions_per_market,max_consecutive_losses,
             require_stop,require_take_profit,block_stale_data,
             block_unresolved_reconciliation,active)
        VALUES(NEWID(),@tenant_id,1,0.25,1.00,2,1,4,1,1,1,1,1);

    IF @tenant_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.engine_controls WHERE tenant_id=@tenant_id)
        INSERT INTO app.engine_controls(tenant_id,mode,new_orders_enabled,pause_reason)
        VALUES(@tenant_id,'SHADOW',0,N'New platform starts in shadow mode');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
