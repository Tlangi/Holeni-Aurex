USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;

 IF EXISTS(SELECT 1 FROM sys.check_constraints
           WHERE parent_object_id=OBJECT_ID(N'app.historical_backfill_jobs')
             AND name=N'CK_backfill_status')
  ALTER TABLE app.historical_backfill_jobs DROP CONSTRAINT CK_backfill_status;
 ALTER TABLE app.historical_backfill_jobs WITH CHECK ADD CONSTRAINT CK_backfill_status
  CHECK(status IN ('NOT_STARTED','DOWNLOADING','DOWNLOADED','VALIDATING','IMPORTED',
                   'PARTIAL','FAILED','RETRY_PENDING','COMPLETE','SUPERSEDED'));

 IF OBJECT_ID(N'app.market_timeframe_fallbacks',N'U') IS NULL
 BEGIN
  CREATE TABLE app.market_timeframe_fallbacks(
   market_id uniqueidentifier NOT NULL,
   missing_timeframe varchar(10) NOT NULL,
   interval_start_utc datetime2(3) NOT NULL,
   interval_end_utc datetime2(3) NOT NULL,
   fallback_timeframe varchar(10) NOT NULL,
   fallback_source varchar(30) NOT NULL,
   fallback_timestamp_utc datetime2(3) NOT NULL,
   quality_state varchar(50) NOT NULL,
   genuine_m1_required bit NOT NULL,
   evidence_detail nvarchar(500) NOT NULL,
   evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_timeframe_fallback_evaluated DEFAULT SYSUTCDATETIME(),
   CONSTRAINT PK_market_timeframe_fallbacks PRIMARY KEY
    (market_id,missing_timeframe,interval_start_utc,fallback_source),
   CONSTRAINT FK_timeframe_fallback_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT CK_timeframe_fallback_direction CHECK(
    missing_timeframe='M1' AND fallback_timeframe='M5'
    AND quality_state='M1_MISSING_M5_FALLBACK_AVAILABLE'),
   CONSTRAINT CK_timeframe_fallback_interval CHECK(interval_end_utc>interval_start_utc)
  );
 END;

 IF OBJECT_ID(N'app.v_canonical_market_candles_m1',N'V') IS NOT NULL
  DROP VIEW app.v_canonical_market_candles_m1;
 EXEC(N'CREATE VIEW app.v_canonical_market_candles_m1 AS
  WITH ranked AS (
   SELECT c.*,ROW_NUMBER() OVER(PARTITION BY c.market_id,c.timestamp_utc ORDER BY
    CASE
     WHEN c.source LIKE ''IG_LIGHTSTREAMER%'' AND c.is_live=1 THEN 10
     WHEN c.source LIKE ''IG_%'' AND c.point_in_time_verified=1 THEN 20
     WHEN c.source=''DUKASCOPY_TICK_BID_ASK'' AND c.research_eligible=1 THEN 30
     WHEN c.source LIKE ''HISTDATA_TICK%'' AND c.research_eligible=1 THEN 40
     WHEN c.research_eligible=1 THEN 50 ELSE 100 END,
    c.ingested_at_utc DESC,c.source) canonical_rank
   FROM app.market_candles_m1 c
   WHERE c.quality_state NOT IN (''REJECTED'',''INCOMPLETE'')
     AND c.instrument_equivalence<>''INDEX_REFERENCE''
  ) SELECT * FROM ranked WHERE canonical_rank=1');

 IF OBJECT_ID(N'app.v_canonical_market_candles_m5',N'V') IS NOT NULL
  DROP VIEW app.v_canonical_market_candles_m5;
 EXEC(N'CREATE VIEW app.v_canonical_market_candles_m5 AS
  WITH ranked AS (
   SELECT c.*,ROW_NUMBER() OVER(PARTITION BY c.market_id,c.timestamp_utc ORDER BY
    CASE WHEN c.source LIKE ''IG_%'' THEN 10
         WHEN c.source=''DERIVED_FROM_M1'' AND c.research_eligible=1 THEN 20
         WHEN c.research_eligible=1 THEN 30 ELSE 100 END,
    c.ingested_at_utc DESC,c.source) canonical_rank
   FROM app.market_candles_m5 c
   WHERE c.quality_state NOT IN (''REJECTED'',''INCOMPLETE'')
     AND c.instrument_equivalence<>''INDEX_REFERENCE''
  ) SELECT * FROM ranked WHERE canonical_rank=1');

 COMMIT TRANSACTION;
 PRINT 'Recent M1 campaign, explicit M5 fallback evidence and unique canonical views installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
