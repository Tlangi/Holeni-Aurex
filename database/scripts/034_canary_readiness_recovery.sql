USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.broker_market_rules',N'current_bid') IS NULL
        ALTER TABLE app.broker_market_rules ADD current_bid decimal(19,8) NULL;
    IF COL_LENGTH(N'app.broker_market_rules',N'current_ask') IS NULL
        ALTER TABLE app.broker_market_rules ADD current_ask decimal(19,8) NULL;

    IF COL_LENGTH(N'app.data_quality_gaps',N'recovery_result') IS NULL
        ALTER TABLE app.data_quality_gaps ADD recovery_result varchar(40) NULL;
    IF COL_LENGTH(N'app.data_quality_gaps',N'recovery_assessed_at_utc') IS NULL
        ALTER TABLE app.data_quality_gaps ADD recovery_assessed_at_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.data_quality_gaps',N'current_execution_relevant_until_utc') IS NULL
        ALTER TABLE app.data_quality_gaps ADD current_execution_relevant_until_utc datetime2(3) NULL;

    IF OBJECT_ID(N'app.provider_history_boundaries',N'U') IS NULL
    BEGIN
        CREATE TABLE app.provider_history_boundaries
        (
            provider_history_boundary_id uniqueidentifier NOT NULL
                CONSTRAINT PK_provider_history_boundaries PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            provider_code varchar(30) NOT NULL,
            timeframe varchar(10) NOT NULL,
            earliest_available_utc datetime2(3) NULL,
            latest_available_utc datetime2(3) NULL,
            last_page_requested int NULL,
            last_page_size int NULL,
            boundary_status varchar(40) NOT NULL,
            provider_limit_reason varchar(120) NULL,
            observed_at_utc datetime2(3) NOT NULL,
            CONSTRAINT FK_provider_history_boundary_market FOREIGN KEY(market_id)
                REFERENCES app.markets(market_id),
            CONSTRAINT UQ_provider_history_boundary UNIQUE(market_id,provider_code,timeframe),
            CONSTRAINT CK_provider_history_boundary_status CHECK(boundary_status IN
                ('OBSERVED','PARTIAL','PROVIDER_LIMIT','QUOTA_DEFERRED','UNAVAILABLE'))
        );
    END;

    COMMIT TRANSACTION;
    PRINT 'Canary readiness recovery migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
