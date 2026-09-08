USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;

 IF COL_LENGTH(N'app.historical_import_batches',N'expected_trading_minutes') IS NULL
 BEGIN
  ALTER TABLE app.historical_import_batches ADD
   expected_trading_minutes bigint NULL,
   observed_trading_minutes bigint NULL,
   coverage_percentage decimal(9,6) NULL,
   largest_unexpected_gap_minutes int NULL,
   unexpected_gap_count int NULL,
   invalid_ohlc_count bigint NULL,
   timestamp_error_count bigint NULL,
   price_anomaly_count bigint NULL,
   bid_ask_complete bit NULL,
   validation_state varchar(30) NOT NULL CONSTRAINT DF_historical_validation_state DEFAULT 'PARSED',
   validation_version varchar(40) NULL,
   validation_details_json nvarchar(max) NULL,
   validated_at_utc datetime2(3) NULL,
   promoted_at_utc datetime2(3) NULL;
 END;

 IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name='CK_historical_validation_state')
  EXEC(N'ALTER TABLE app.historical_import_batches ADD CONSTRAINT CK_historical_validation_state
  CHECK(validation_state IN (''DOWNLOADED'',''PARSED'',''STRUCTURALLY_VALID'',''CALENDAR_VALIDATED'',
   ''CROSS_SOURCE_VALIDATED'',''MAPPING_APPROVED'',''PROMOTION_ELIGIBLE'',''PROMOTED'',''QUARANTINED'',''REJECTED''))');

 IF OBJECT_ID(N'app.historical_partition_gaps',N'U') IS NULL
 BEGIN
  CREATE TABLE app.historical_partition_gaps(
   historical_partition_gap_id uniqueidentifier NOT NULL CONSTRAINT PK_historical_partition_gaps PRIMARY KEY,
   import_batch_id uniqueidentifier NOT NULL,
   gap_start_utc datetime2(3) NOT NULL,
   gap_end_utc datetime2(3) NOT NULL,
   missing_minutes int NOT NULL,
   reason_code varchar(40) NOT NULL,
   is_unexpected bit NOT NULL,
   evidence_detail nvarchar(500) NULL,
   classified_at_utc datetime2(3) NOT NULL CONSTRAINT DF_historical_gap_classified DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_historical_gap_batch FOREIGN KEY(import_batch_id) REFERENCES app.historical_import_batches(import_batch_id),
   CONSTRAINT CK_historical_gap_reason CHECK(reason_code IN ('EXPECTED_WEEKEND','EXPECTED_MARKET_CLOSED',
    'EXPECTED_HOLIDAY','EXPECTED_SESSION_BREAK','LOW_LIQUIDITY_NO_UPDATE','SOURCE_MISSING',
    'DOWNLOAD_FAILURE','UNKNOWN_GAP'))
  );
  CREATE INDEX IX_historical_gap_batch ON app.historical_partition_gaps(import_batch_id,gap_start_utc);
 END;

 IF OBJECT_ID(N'app.historical_partition_reconciliations',N'U') IS NULL
 BEGIN
  CREATE TABLE app.historical_partition_reconciliations(
   historical_partition_reconciliation_id uniqueidentifier NOT NULL CONSTRAINT PK_historical_partition_reconciliations PRIMARY KEY,
   import_batch_id uniqueidentifier NOT NULL,
   market_id uniqueidentifier NOT NULL,
   comparison_source varchar(40) NOT NULL,
   partition_start_utc datetime2(3) NOT NULL,
   partition_end_utc datetime2(3) NOT NULL,
   comparison_start_utc datetime2(3) NULL,
   comparison_end_utc datetime2(3) NULL,
   comparable_candles int NOT NULL,
   within_tolerance_candles int NOT NULL,
   match_percentage decimal(9,6) NULL,
   open_delta decimal(19,8) NULL,
   high_delta decimal(19,8) NULL,
   low_delta decimal(19,8) NULL,
   close_delta decimal(19,8) NULL,
   timestamp_aligned bit NOT NULL,
   coverage_overlap decimal(9,6) NULL,
   status varchar(30) NOT NULL,
   evidence_sha256 char(64) NULL,
   evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_partition_recon_evaluated DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_partition_recon_batch FOREIGN KEY(import_batch_id) REFERENCES app.historical_import_batches(import_batch_id),
   CONSTRAINT FK_partition_recon_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT UQ_partition_recon UNIQUE(import_batch_id,comparison_source),
   CONSTRAINT CK_partition_recon_status CHECK(status IN ('NO_OVERLAP','INSUFFICIENT','PASS','FAIL'))
  );
 END;

 IF OBJECT_ID(N'app.historical_backfill_notifications',N'U') IS NULL
  CREATE TABLE app.historical_backfill_notifications(
   notification_key varchar(100) NOT NULL CONSTRAINT PK_historical_backfill_notifications PRIMARY KEY,
   terminal_state varchar(30) NOT NULL,
   total_partitions int NOT NULL,
   complete_partitions int NOT NULL,
   failed_partitions int NOT NULL,
   claimed_at_utc datetime2(3) NOT NULL,
   sent_at_utc datetime2(3) NULL,
   delivery_status varchar(20) NOT NULL,
   error_detail nvarchar(1000) NULL,
   CONSTRAINT CK_backfill_notification_status CHECK(delivery_status IN ('CLAIMED','SENT','FAILED'))
  );

 COMMIT TRANSACTION;
 PRINT 'Historical partition validation and notification governance installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
