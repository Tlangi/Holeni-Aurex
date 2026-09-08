USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.historical_backfill_jobs',N'U') IS NULL
 BEGIN
  CREATE TABLE app.historical_backfill_jobs(
   backfill_job_id uniqueidentifier NOT NULL CONSTRAINT PK_historical_backfill_jobs PRIMARY KEY,
   market_id uniqueidentifier NOT NULL,vendor varchar(30) NOT NULL,vendor_symbol varchar(40) NOT NULL,
   partition_start_utc datetime2(3) NOT NULL,partition_end_utc datetime2(3) NOT NULL,
   source_format varchar(40) NOT NULL,priority int NOT NULL,status varchar(20) NOT NULL,
   attempt_count int NOT NULL CONSTRAINT DF_backfill_attempt DEFAULT 0,
   claimed_at_utc datetime2(3) NULL,heartbeat_at_utc datetime2(3) NULL,completed_at_utc datetime2(3) NULL,
   next_attempt_at_utc datetime2(3) NULL,import_batch_id uniqueidentifier NULL,
   output_path nvarchar(500) NULL,last_error_code varchar(80) NULL,last_error_detail nvarchar(1000) NULL,
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_backfill_created DEFAULT SYSUTCDATETIME(),
   updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_backfill_updated DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_backfill_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT FK_backfill_batch FOREIGN KEY(import_batch_id) REFERENCES app.historical_import_batches(import_batch_id),
   CONSTRAINT UQ_backfill_partition UNIQUE(market_id,vendor,source_format,partition_start_utc,partition_end_utc),
   CONSTRAINT CK_backfill_status CHECK(status IN ('NOT_STARTED','DOWNLOADING','DOWNLOADED','VALIDATING','IMPORTED','PARTIAL','FAILED','RETRY_PENDING','COMPLETE')),
   CONSTRAINT CK_backfill_partition CHECK(partition_end_utc>partition_start_utc)
  );
  CREATE INDEX IX_backfill_claim ON app.historical_backfill_jobs(status,next_attempt_at_utc,priority,partition_start_utc)
   INCLUDE(market_id,vendor,vendor_symbol,source_format,attempt_count);
 END;
 COMMIT TRANSACTION;
 PRINT 'Resumable bounded historical backfill job ledger installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
