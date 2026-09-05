USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.live_candle_snapshots',N'U') IS NULL
    BEGIN
        CREATE TABLE app.live_candle_snapshots
        (
            market_id uniqueidentifier NOT NULL,
            timeframe varchar(5) NOT NULL,
            open_time_utc datetime2(3) NOT NULL,
            [open] decimal(19,8) NOT NULL,
            high decimal(19,8) NOT NULL,
            low decimal(19,8) NOT NULL,
            [close] decimal(19,8) NOT NULL,
            bid_close decimal(19,8) NULL,
            ask_close decimal(19,8) NULL,
            spread_close decimal(19,8) NULL,
            tick_count bigint NOT NULL CONSTRAINT DF_live_candle_ticks DEFAULT 0,
            source_event_utc datetime2(3) NOT NULL,
            source_sequence bigint NOT NULL,
            completed bit NOT NULL CONSTRAINT DF_live_candle_completed DEFAULT 0,
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_live_candle_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT PK_live_candle_snapshots PRIMARY KEY(market_id,timeframe),
            CONSTRAINT FK_live_candle_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_live_candle_timeframe CHECK(timeframe IN ('M5','M15','M30','H1','H4','D1')),
            CONSTRAINT CK_live_candle_prices CHECK(high>=[open] AND high>=[close] AND low<=[open] AND low<=[close] AND high>=low)
        );
        CREATE INDEX IX_live_candle_updates ON app.live_candle_snapshots(updated_at_utc,market_id);
    END;

    IF COL_LENGTH(N'app.research_jobs',N'market_id') IS NULL ALTER TABLE app.research_jobs ADD market_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.research_jobs',N'timeframe') IS NULL ALTER TABLE app.research_jobs ADD timeframe varchar(5) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'model_family') IS NULL ALTER TABLE app.research_jobs ADD model_family varchar(80) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'current_phase') IS NULL ALTER TABLE app.research_jobs ADD current_phase varchar(80) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'phase_number') IS NULL ALTER TABLE app.research_jobs ADD phase_number int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'total_phases') IS NULL ALTER TABLE app.research_jobs ADD total_phases int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'completed_work_units') IS NULL ALTER TABLE app.research_jobs ADD completed_work_units int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'total_work_units') IS NULL ALTER TABLE app.research_jobs ADD total_work_units int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'records_processed') IS NULL ALTER TABLE app.research_jobs ADD records_processed bigint NULL;
    IF COL_LENGTH(N'app.research_jobs',N'folds_completed') IS NULL ALTER TABLE app.research_jobs ADD folds_completed int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'total_folds') IS NULL ALTER TABLE app.research_jobs ADD total_folds int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'candidates_completed') IS NULL ALTER TABLE app.research_jobs ADD candidates_completed int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'total_candidates') IS NULL ALTER TABLE app.research_jobs ADD total_candidates int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'trials_completed') IS NULL ALTER TABLE app.research_jobs ADD trials_completed int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'total_trials') IS NULL ALTER TABLE app.research_jobs ADD total_trials int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'last_heartbeat_utc') IS NULL ALTER TABLE app.research_jobs ADD last_heartbeat_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'eta_seconds') IS NULL ALTER TABLE app.research_jobs ADD eta_seconds int NULL;
    IF COL_LENGTH(N'app.research_jobs',N'eta_confidence') IS NULL ALTER TABLE app.research_jobs ADD eta_confidence varchar(10) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'eta_basis') IS NULL ALTER TABLE app.research_jobs ADD eta_basis nvarchar(300) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'warning_message') IS NULL ALTER TABLE app.research_jobs ADD warning_message nvarchar(500) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'failure_code') IS NULL ALTER TABLE app.research_jobs ADD failure_code varchar(80) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'cancel_requested_at_utc') IS NULL ALTER TABLE app.research_jobs ADD cancel_requested_at_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'code_version') IS NULL ALTER TABLE app.research_jobs ADD code_version varchar(80) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'feature_version') IS NULL ALTER TABLE app.research_jobs ADD feature_version varchar(80) NULL;
    IF COL_LENGTH(N'app.research_jobs',N'dataset_identifier') IS NULL ALTER TABLE app.research_jobs ADD dataset_identifier varchar(128) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_research_jobs_market')
        ALTER TABLE app.research_jobs ADD CONSTRAINT FK_research_jobs_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id);

    IF OBJECT_ID(N'app.research_job_phase_history',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_job_phase_history
        (
            phase_history_id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_research_job_phase_history PRIMARY KEY,
            research_job_id uniqueidentifier NOT NULL,
            phase varchar(80) NOT NULL,
            phase_number int NULL,
            completed_work_units int NULL,
            total_work_units int NULL,
            status_message nvarchar(500) NULL,
            recorded_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_phase_recorded DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_research_phase_job FOREIGN KEY(research_job_id) REFERENCES app.research_jobs(research_job_id)
        );
        CREATE INDEX IX_research_phase_job ON app.research_job_phase_history(research_job_id,recorded_at_utc);
    END;

    COMMIT TRANSACTION;
    PRINT 'Aurex streaming, quality and training observability migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
