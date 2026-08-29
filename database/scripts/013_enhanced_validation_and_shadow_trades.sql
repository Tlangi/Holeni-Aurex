USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.model_evaluations',N'walk_forward_windows') IS NULL ALTER TABLE app.model_evaluations ADD walk_forward_windows int NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'trade_count') IS NULL ALTER TABLE app.model_evaluations ADD trade_count int NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'win_rate') IS NULL ALTER TABLE app.model_evaluations ADD win_rate decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'profit_factor') IS NULL ALTER TABLE app.model_evaluations ADD profit_factor decimal(19,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'expectancy') IS NULL ALTER TABLE app.model_evaluations ADD expectancy decimal(19,10) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'max_drawdown') IS NULL ALTER TABLE app.model_evaluations ADD max_drawdown decimal(19,10) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'sharpe_ratio') IS NULL ALTER TABLE app.model_evaluations ADD sharpe_ratio decimal(19,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'sortino_ratio') IS NULL ALTER TABLE app.model_evaluations ADD sortino_ratio decimal(19,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'precision_buy') IS NULL ALTER TABLE app.model_evaluations ADD precision_buy decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'precision_sell') IS NULL ALTER TABLE app.model_evaluations ADD precision_sell decimal(12,8) NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'baseline_outperformed') IS NULL ALTER TABLE app.model_evaluations ADD baseline_outperformed bit NULL;
    IF COL_LENGTH(N'app.model_evaluations',N'cost_assumption_bps') IS NULL ALTER TABLE app.model_evaluations ADD cost_assumption_bps decimal(12,6) NULL;

    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_models_status')
        ALTER TABLE app.model_versions DROP CONSTRAINT CK_models_status;
    ALTER TABLE app.model_versions WITH CHECK ADD CONSTRAINT CK_models_status
        CHECK(status IN ('REGISTERED','CANDIDATE','VALIDATING','VALIDATED','REJECTED','SUSPENDED','RETIRED'));

    IF OBJECT_ID(N'app.model_walk_forward_windows',N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_walk_forward_windows
        (
            walk_forward_window_id uniqueidentifier NOT NULL CONSTRAINT PK_walk_forward_windows PRIMARY KEY,
            model_evaluation_id uniqueidentifier NOT NULL,
            window_number int NOT NULL,
            training_start_utc datetime2(3) NOT NULL,
            training_end_utc datetime2(3) NOT NULL,
            validation_start_utc datetime2(3) NOT NULL,
            validation_end_utc datetime2(3) NOT NULL,
            training_rows int NOT NULL,
            validation_rows int NOT NULL,
            auc decimal(12,8) NULL,
            trade_count int NOT NULL,
            win_rate decimal(12,8) NOT NULL,
            profit_factor decimal(19,8) NULL,
            expectancy decimal(19,10) NOT NULL,
            max_drawdown decimal(19,10) NOT NULL,
            sharpe_ratio decimal(19,8) NULL,
            sortino_ratio decimal(19,8) NULL,
            precision_buy decimal(12,8) NULL,
            precision_sell decimal(12,8) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_walk_forward_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_walk_forward_evaluation FOREIGN KEY(model_evaluation_id) REFERENCES app.model_evaluations(model_evaluation_id),
            CONSTRAINT UQ_walk_forward_window UNIQUE(model_evaluation_id,window_number)
        );
    END;

    IF OBJECT_ID(N'app.model_baseline_results',N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_baseline_results
        (
            baseline_result_id uniqueidentifier NOT NULL CONSTRAINT PK_model_baseline_results PRIMARY KEY,
            model_evaluation_id uniqueidentifier NOT NULL,
            baseline_name varchar(40) NOT NULL,
            trade_count int NOT NULL,
            win_rate decimal(12,8) NOT NULL,
            profit_factor decimal(19,8) NULL,
            expectancy decimal(19,10) NOT NULL,
            max_drawdown decimal(19,10) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_baseline_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_baseline_evaluation FOREIGN KEY(model_evaluation_id) REFERENCES app.model_evaluations(model_evaluation_id),
            CONSTRAINT UQ_baseline_name UNIQUE(model_evaluation_id,baseline_name),
            CONSTRAINT CK_baseline_name CHECK(baseline_name IN ('ALWAYS_HOLD','SMA','MOMENTUM','RANDOM'))
        );
    END;

    IF OBJECT_ID(N'app.shadow_trades',N'U') IS NULL
    BEGIN
        CREATE TABLE app.shadow_trades
        (
            shadow_trade_id uniqueidentifier NOT NULL CONSTRAINT PK_shadow_trades PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            order_intent_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            direction varchar(4) NOT NULL,
            size decimal(19,8) NOT NULL,
            entry_price decimal(19,8) NOT NULL,
            stop_price decimal(19,8) NOT NULL,
            target_price decimal(19,8) NOT NULL,
            value_per_price_point_zar decimal(19,8) NOT NULL,
            estimated_entry_cost_zar decimal(19,8) NOT NULL,
            current_price decimal(19,8) NOT NULL,
            unrealized_pnl_zar decimal(19,8) NOT NULL CONSTRAINT DF_shadow_unrealized DEFAULT 0,
            exit_price decimal(19,8) NULL,
            realized_pnl_zar decimal(19,8) NULL,
            exit_reason varchar(40) NULL,
            status varchar(20) NOT NULL,
            entry_candle_id bigint NOT NULL,
            last_candle_id bigint NOT NULL,
            opened_at_utc datetime2(3) NOT NULL,
            closed_at_utc datetime2(3) NULL,
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_shadow_updated DEFAULT SYSUTCDATETIME(),
            row_version rowversion NOT NULL,
            CONSTRAINT FK_shadow_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_shadow_intent FOREIGN KEY(order_intent_id) REFERENCES app.order_intents(order_intent_id),
            CONSTRAINT FK_shadow_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_shadow_entry_candle FOREIGN KEY(entry_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT FK_shadow_last_candle FOREIGN KEY(last_candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT UQ_shadow_intent UNIQUE(order_intent_id),
            CONSTRAINT CK_shadow_direction CHECK(direction IN ('BUY','SELL')),
            CONSTRAINT CK_shadow_status CHECK(status IN ('OPEN','CLOSED','CANCELLED')),
            CONSTRAINT CK_shadow_prices CHECK(size>0 AND entry_price>0 AND stop_price>0 AND target_price>0)
        );
        CREATE INDEX IX_shadow_trades_tenant_status ON app.shadow_trades(tenant_id,status,opened_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.shadow_trade_events',N'U') IS NULL
    BEGIN
        CREATE TABLE app.shadow_trade_events
        (
            shadow_trade_event_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_shadow_trade_events PRIMARY KEY,
            shadow_trade_id uniqueidentifier NOT NULL,
            event_type varchar(40) NOT NULL,
            candle_id bigint NOT NULL,
            price decimal(19,8) NOT NULL,
            pnl_zar decimal(19,8) NOT NULL,
            details_json nvarchar(max) NULL,
            occurred_at_utc datetime2(3) NOT NULL,
            CONSTRAINT FK_shadow_event_trade FOREIGN KEY(shadow_trade_id) REFERENCES app.shadow_trades(shadow_trade_id),
            CONSTRAINT FK_shadow_event_candle FOREIGN KEY(candle_id) REFERENCES app.candles(candle_id),
            CONSTRAINT CK_shadow_event_json CHECK(details_json IS NULL OR ISJSON(details_json)=1)
        );
        CREATE INDEX IX_shadow_trade_events_trade ON app.shadow_trade_events(shadow_trade_id,occurred_at_utc);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
