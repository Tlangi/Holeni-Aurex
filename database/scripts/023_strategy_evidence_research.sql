USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.data_quality_segments',N'U') IS NULL
    BEGIN
        CREATE TABLE app.data_quality_segments
        (
            data_quality_segment_id uniqueidentifier NOT NULL CONSTRAINT PK_data_quality_segments PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            provider varchar(20) NOT NULL,
            timeframe varchar(10) NOT NULL,
            segment_start_utc datetime2(3) NOT NULL,
            segment_end_utc datetime2(3) NOT NULL,
            expected_interval_minutes int NOT NULL,
            actual_rows int NOT NULL,
            expected_rows int NOT NULL,
            completeness_pct decimal(12,8) NOT NULL,
            gap_count int NOT NULL,
            largest_gap_minutes int NOT NULL,
            purpose varchar(30) NOT NULL,
            quality_status varchar(20) NOT NULL,
            source_reference nvarchar(300) NULL,
            details_json nvarchar(max) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_quality_segments_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_quality_segments_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_quality_segments_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_quality_segments_provider CHECK(provider IN ('DUKASCOPY','IG')),
            CONSTRAINT CK_quality_segments_timeframe CHECK(timeframe IN ('M5','M15')),
            CONSTRAINT CK_quality_segments_purpose CHECK(purpose IN ('HISTORICAL_RESEARCH','TRAINING','BACKTEST','LIVE_EXECUTION')),
            CONSTRAINT CK_quality_segments_status CHECK(quality_status IN ('PASS','WARN','FAIL','KNOWN_GAP')),
            CONSTRAINT CK_quality_segments_counts CHECK(expected_interval_minutes>0 AND actual_rows>=0 AND expected_rows>=0 AND gap_count>=0 AND largest_gap_minutes>=0),
            CONSTRAINT CK_quality_segments_json CHECK(details_json IS NULL OR ISJSON(details_json)=1),
            CONSTRAINT UQ_quality_segments_identity UNIQUE(market_id,provider,timeframe,segment_start_utc,segment_end_utc,purpose)
        );
        CREATE INDEX IX_quality_segments_market_time ON app.data_quality_segments(market_id,timeframe,segment_end_utc DESC);
    END;

    IF OBJECT_ID(N'app.data_quality_gaps',N'U') IS NULL
    BEGIN
        CREATE TABLE app.data_quality_gaps
        (
            data_quality_gap_id uniqueidentifier NOT NULL CONSTRAINT PK_data_quality_gaps PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            timeframe varchar(10) NOT NULL,
            provider_before varchar(20) NULL,
            provider_after varchar(20) NULL,
            gap_start_utc datetime2(3) NOT NULL,
            gap_end_utc datetime2(3) NOT NULL,
            gap_minutes int NOT NULL,
            classification varchar(40) NOT NULL,
            execution_blocking bit NOT NULL,
            reason nvarchar(400) NOT NULL,
            detected_at_utc datetime2(3) NOT NULL CONSTRAINT DF_quality_gaps_detected DEFAULT SYSUTCDATETIME(),
            resolved_at_utc datetime2(3) NULL,
            CONSTRAINT FK_quality_gaps_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_quality_gaps_timeframe CHECK(timeframe IN ('M5','M15')),
            CONSTRAINT CK_quality_gaps_class CHECK(classification IN ('EXPECTED_PROVIDER_BOUNDARY','WEEKEND','MARKET_CLOSED','DECLARED_IMPORT_BOUNDARY','UNEXPECTED_MISSING_DATA','LIVE_STREAM_INTERRUPTION')),
            CONSTRAINT CK_quality_gaps_minutes CHECK(gap_minutes>=0)
        );
        CREATE INDEX IX_quality_gaps_market_time ON app.data_quality_gaps(market_id,gap_start_utc DESC);
    END;

    IF OBJECT_ID(N'app.execution_quality_snapshots',N'U') IS NULL
    BEGIN
        CREATE TABLE app.execution_quality_snapshots
        (
            execution_quality_snapshot_id uniqueidentifier NOT NULL CONSTRAINT PK_execution_quality_snapshots PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            m5_fresh bit NOT NULL,
            m15_fresh bit NOT NULL,
            bid_fresh bit NOT NULL,
            ask_fresh bit NOT NULL,
            spread_fresh bit NOT NULL,
            broker_rules_fresh bit NOT NULL,
            market_session_valid bit NOT NULL,
            latest_candle_completed bit NOT NULL,
            recent_unexpected_gap_count int NOT NULL,
            historical_research_quality varchar(20) NOT NULL,
            training_quality varchar(20) NOT NULL,
            recent_ig_continuity varchar(20) NOT NULL,
            execution_price_freshness varchar(20) NOT NULL,
            cross_provider_continuity varchar(20) NOT NULL,
            overall_execution_quality varchar(20) NOT NULL,
            reasons_json nvarchar(max) NOT NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_execution_quality_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_execution_quality_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_execution_quality_gap_count CHECK(recent_unexpected_gap_count>=0),
            CONSTRAINT CK_execution_quality_reasons CHECK(ISJSON(reasons_json)=1)
        );
        CREATE INDEX IX_execution_quality_market_time ON app.execution_quality_snapshots(market_id,evaluated_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.cost_model_versions',N'U') IS NULL
    BEGIN
        CREATE TABLE app.cost_model_versions
        (
            cost_model_version_id uniqueidentifier NOT NULL CONSTRAINT PK_cost_model_versions PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            version varchar(80) NOT NULL,
            provider varchar(20) NOT NULL,
            source_start_utc datetime2(3) NOT NULL,
            source_end_utc datetime2(3) NOT NULL,
            observation_count int NOT NULL,
            optimistic_percentile decimal(6,3) NOT NULL,
            normal_percentile decimal(6,3) NOT NULL,
            stressed_percentile decimal(6,3) NOT NULL,
            configuration_hash char(64) NOT NULL,
            status varchar(20) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_cost_models_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_cost_models_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_cost_models_version UNIQUE(market_id,version),
            CONSTRAINT CK_cost_models_provider CHECK(provider='IG'),
            CONSTRAINT CK_cost_models_status CHECK(status IN ('CURRENT','RETIRED','INSUFFICIENT'))
        );
    END;

    IF OBJECT_ID(N'app.cost_model_buckets',N'U') IS NULL
    BEGIN
        CREATE TABLE app.cost_model_buckets
        (
            cost_model_bucket_id uniqueidentifier NOT NULL CONSTRAINT PK_cost_model_buckets PRIMARY KEY,
            cost_model_version_id uniqueidentifier NOT NULL,
            bucket_type varchar(30) NOT NULL,
            bucket_key varchar(80) NOT NULL,
            session_name varchar(40) NULL,
            weekday_number tinyint NULL,
            quarter_hour tinyint NULL,
            volatility_regime varchar(20) NULL,
            observation_count int NOT NULL,
            mean_spread decimal(19,8) NOT NULL,
            median_spread decimal(19,8) NOT NULL,
            p75_spread decimal(19,8) NOT NULL,
            p90_spread decimal(19,8) NOT NULL,
            p95_spread decimal(19,8) NOT NULL,
            max_spread decimal(19,8) NOT NULL,
            CONSTRAINT FK_cost_buckets_version FOREIGN KEY(cost_model_version_id) REFERENCES app.cost_model_versions(cost_model_version_id),
            CONSTRAINT UQ_cost_buckets_key UNIQUE(cost_model_version_id,bucket_type,bucket_key),
            CONSTRAINT CK_cost_buckets_count CHECK(observation_count>0)
        );
    END;

    IF OBJECT_ID(N'app.research_experiments',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_experiments
        (
            experiment_id uniqueidentifier NOT NULL CONSTRAINT PK_research_experiments PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            strategy_version varchar(80) NOT NULL,
            feature_version varchar(80) NOT NULL,
            label_version varchar(80) NOT NULL,
            model_version varchar(100) NULL,
            regime_version varchar(80) NOT NULL,
            cost_model_version varchar(80) NOT NULL,
            retrain_type varchar(30) NOT NULL,
            training_start_utc datetime2(3) NULL,
            training_end_utc datetime2(3) NULL,
            validation_start_utc datetime2(3) NULL,
            validation_end_utc datetime2(3) NULL,
            holdout_start_utc datetime2(3) NULL,
            holdout_end_utc datetime2(3) NULL,
            configuration_hash char(64) NOT NULL,
            code_commit varchar(80) NULL,
            status varchar(30) NOT NULL,
            notes nvarchar(1000) NULL,
            outcome_json nvarchar(max) NULL,
            started_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_experiments_started DEFAULT SYSUTCDATETIME(),
            completed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_research_experiments_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_research_experiments_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_research_retrain_type CHECK(retrain_type IN ('SCHEDULED_RETRAIN','RESEARCH_RETRAIN','DIAGNOSTIC_REPLAY')),
            CONSTRAINT CK_research_experiment_status CHECK(status IN ('REGISTERED','RUNNING','COMPLETED','FAILED','REJECTED')),
            CONSTRAINT CK_research_outcome_json CHECK(outcome_json IS NULL OR ISJSON(outcome_json)=1)
        );
        CREATE INDEX IX_research_experiments_market_time ON app.research_experiments(market_id,started_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.research_diagnostics',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_diagnostics
        (
            research_diagnostic_id uniqueidentifier NOT NULL CONSTRAINT PK_research_diagnostics PRIMARY KEY,
            experiment_id uniqueidentifier NOT NULL,
            replay_run_id uniqueidentifier NULL,
            diagnostic_version varchar(80) NOT NULL,
            summary_json nvarchar(max) NOT NULL,
            decomposition_json nvarchar(max) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_diagnostics_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_research_diagnostics_experiment FOREIGN KEY(experiment_id) REFERENCES app.research_experiments(experiment_id),
            CONSTRAINT FK_research_diagnostics_replay FOREIGN KEY(replay_run_id) REFERENCES app.replay_runs(replay_run_id),
            CONSTRAINT CK_research_summary_json CHECK(ISJSON(summary_json)=1),
            CONSTRAINT CK_research_decomposition_json CHECK(ISJSON(decomposition_json)=1)
        );
    END;

    IF COL_LENGTH(N'app.replay_runs',N'experiment_id') IS NULL ALTER TABLE app.replay_runs ADD experiment_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.replay_runs',N'cost_model_version_id') IS NULL ALTER TABLE app.replay_runs ADD cost_model_version_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.replay_trades',N'gross_pnl_zar') IS NULL ALTER TABLE app.replay_trades ADD gross_pnl_zar decimal(19,6) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'mae_points') IS NULL ALTER TABLE app.replay_trades ADD mae_points decimal(19,8) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'mfe_points') IS NULL ALTER TABLE app.replay_trades ADD mfe_points decimal(19,8) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'r_multiple') IS NULL ALTER TABLE app.replay_trades ADD r_multiple decimal(19,8) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'holding_minutes') IS NULL ALTER TABLE app.replay_trades ADD holding_minutes int NULL;
    IF COL_LENGTH(N'app.replay_trades',N'prediction_confidence') IS NULL ALTER TABLE app.replay_trades ADD prediction_confidence decimal(12,8) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'session_name') IS NULL ALTER TABLE app.replay_trades ADD session_name varchar(40) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'trend_regime') IS NULL ALTER TABLE app.replay_trades ADD trend_regime varchar(30) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'volatility_regime') IS NULL ALTER TABLE app.replay_trades ADD volatility_regime varchar(20) NULL;
    IF COL_LENGTH(N'app.replay_trades',N'entry_reason') IS NULL ALTER TABLE app.replay_trades ADD entry_reason varchar(50) NULL;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
