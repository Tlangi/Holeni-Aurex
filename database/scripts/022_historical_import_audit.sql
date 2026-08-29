USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.historical_import_runs', N'U') IS NULL
    BEGIN
        CREATE TABLE app.historical_import_runs
        (
            historical_import_run_id uniqueidentifier NOT NULL
                CONSTRAINT PK_historical_import_runs PRIMARY KEY,
            provider varchar(30) NOT NULL,
            market_id uniqueidentifier NOT NULL,
            file_name nvarchar(260) NOT NULL,
            file_sha256 char(64) NOT NULL,
            price_side varchar(10) NOT NULL,
            source_timeframe varchar(10) NOT NULL,
            source_start_utc datetime2(3) NULL,
            source_end_utc datetime2(3) NULL,
            rows_read int NOT NULL,
            accepted_m5 int NOT NULL,
            accepted_m15 int NOT NULL,
            invalid_rows int NOT NULL,
            persisted_m5 int NOT NULL,
            persisted_m15 int NOT NULL,
            status varchar(20) NOT NULL,
            imported_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_historical_import_runs_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_historical_import_runs_market
                FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_historical_import_runs_hash UNIQUE(file_sha256),
            CONSTRAINT CK_historical_import_provider CHECK(provider='DUKASCOPY'),
            CONSTRAINT CK_historical_import_side CHECK(price_side IN ('BID','ASK','MID')),
            CONSTRAINT CK_historical_import_timeframe CHECK(source_timeframe='M5'),
            CONSTRAINT CK_historical_import_status CHECK(status IN ('COMPLETED','FAILED')),
            CONSTRAINT CK_historical_import_counts CHECK
                (rows_read>=0 AND accepted_m5>=0 AND accepted_m15>=0 AND invalid_rows>=0
                 AND persisted_m5>=0 AND persisted_m15>=0)
        );
        CREATE INDEX IX_historical_import_runs_market_time
            ON app.historical_import_runs(market_id,imported_at_utc DESC);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
