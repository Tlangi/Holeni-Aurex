USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.historical_import_batches',N'U') IS NULL
 CREATE TABLE app.historical_import_batches(
  import_batch_id uniqueidentifier NOT NULL CONSTRAINT PK_historical_import_batches PRIMARY KEY,
  market_id uniqueidentifier NOT NULL, vendor varchar(30) NOT NULL, vendor_symbol varchar(40) NOT NULL,
  source_format varchar(40) NOT NULL, price_completeness varchar(20) NOT NULL,
  requested_start_utc datetime2(3) NULL, requested_end_utc datetime2(3) NULL,
  actual_start_utc datetime2(3) NULL, actual_end_utc datetime2(3) NULL,
  downloaded_at_utc datetime2(3) NULL, source_timezone varchar(80) NOT NULL,
  row_count bigint NOT NULL CONSTRAINT DF_historical_batches_rows DEFAULT 0,
  accepted_count bigint NOT NULL CONSTRAINT DF_historical_batches_accepted DEFAULT 0,
  rejected_count bigint NOT NULL CONSTRAINT DF_historical_batches_rejected DEFAULT 0,
  duplicate_count bigint NOT NULL CONSTRAINT DF_historical_batches_duplicate DEFAULT 0,
  gap_count bigint NOT NULL CONSTRAINT DF_historical_batches_gaps DEFAULT 0,
  payload_sha256 char(64) NULL, parser_version varchar(40) NOT NULL,
  conversion_rules nvarchar(1000) NOT NULL, status varchar(20) NOT NULL,
  error_code varchar(80) NULL, error_detail nvarchar(1000) NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_historical_batches_created DEFAULT SYSUTCDATETIME(),
  updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_historical_batches_updated DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_historical_batches_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT CK_historical_batches_status CHECK(status IN ('NOT_STARTED','DOWNLOADING','DOWNLOADED','VALIDATING','IMPORTED','PARTIAL','FAILED','RETRY_PENDING','COMPLETE')),
  CONSTRAINT CK_historical_batches_prices CHECK(price_completeness IN ('BID_ASK_FULL','BID_ONLY','MID_ONLY'))
 );
 IF OBJECT_ID(N'app.market_candles_m1',N'U') IS NULL
 CREATE TABLE app.market_candles_m1(
  market_id uniqueidentifier NOT NULL, timestamp_utc datetime2(3) NOT NULL, source varchar(30) NOT NULL,
  source_symbol varchar(40) NOT NULL, source_timezone varchar(80) NOT NULL,
  bid_open decimal(19,8) NULL,bid_high decimal(19,8) NULL,bid_low decimal(19,8) NULL,bid_close decimal(19,8) NULL,
  ask_open decimal(19,8) NULL,ask_high decimal(19,8) NULL,ask_low decimal(19,8) NULL,ask_close decimal(19,8) NULL,
  mid_open decimal(19,8) NULL,mid_high decimal(19,8) NULL,mid_low decimal(19,8) NULL,mid_close decimal(19,8) NULL,
  spread_open decimal(19,8) NULL,spread_close decimal(19,8) NULL,spread_min decimal(19,8) NULL,
  spread_max decimal(19,8) NULL,spread_mean decimal(19,8) NULL,tick_count bigint NOT NULL,
  price_completeness varchar(20) NOT NULL,quality_state varchar(20) NOT NULL,
  instrument_equivalence varchar(20) NOT NULL,import_batch_id uniqueidentifier NULL,
  is_historical_backfill bit NOT NULL,is_live bit NOT NULL,is_derived bit NOT NULL,
  point_in_time_verified bit NOT NULL,research_eligible bit NOT NULL,
  ingested_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_m1_ingested DEFAULT SYSUTCDATETIME(),
  CONSTRAINT PK_market_candles_m1 PRIMARY KEY(market_id,timestamp_utc,source),
  CONSTRAINT FK_market_m1_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT FK_market_m1_batch FOREIGN KEY(import_batch_id) REFERENCES app.historical_import_batches(import_batch_id),
  CONSTRAINT CK_market_m1_prices CHECK(price_completeness IN ('BID_ASK_FULL','BID_ONLY','MID_ONLY')),
  CONSTRAINT CK_market_m1_quality CHECK(quality_state IN ('VALIDATED','GOOD','ACCEPTABLE','DEGRADED','INCOMPLETE','UNVERIFIED','REJECTED')),
  CONSTRAINT CK_market_m1_equivalence CHECK(instrument_equivalence IN ('EXACT_PAIR','CLOSE_PROXY','INDEX_REFERENCE','BROKER_SPECIFIC','UNVERIFIED')),
  CONSTRAINT CK_market_m1_no_false_spread CHECK(price_completeness='BID_ASK_FULL' OR (ask_open IS NULL AND ask_high IS NULL AND ask_low IS NULL AND ask_close IS NULL AND spread_open IS NULL AND spread_close IS NULL AND spread_min IS NULL AND spread_max IS NULL AND spread_mean IS NULL))
 );
 CREATE INDEX IX_market_m1_source_time ON app.market_candles_m1(source,market_id,timestamp_utc DESC)
  INCLUDE(quality_state,price_completeness,research_eligible);
 IF OBJECT_ID(N'app.market_candles_m5',N'U') IS NULL
 SELECT TOP(0) * INTO app.market_candles_m5 FROM app.market_candles_m1;
 IF NOT EXISTS(SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID(N'app.market_candles_m5') AND type='PK')
  ALTER TABLE app.market_candles_m5 ADD CONSTRAINT PK_market_candles_m5 PRIMARY KEY(market_id,timestamp_utc,source);
 IF OBJECT_ID(N'app.m1_m5_reconciliation',N'U') IS NULL
 CREATE TABLE app.m1_m5_reconciliation(
  reconciliation_id uniqueidentifier NOT NULL CONSTRAINT PK_m1_m5_reconciliation PRIMARY KEY,
  market_id uniqueidentifier NOT NULL,m1_source varchar(30) NOT NULL,m5_source varchar(30) NOT NULL,
  bucket_utc datetime2(3) NOT NULL,m1_count tinyint NOT NULL,m1_complete bit NOT NULL,
  open_delta decimal(19,8) NULL,high_delta decimal(19,8) NULL,low_delta decimal(19,8) NULL,close_delta decimal(19,8) NULL,
  timestamp_aligned bit NOT NULL,within_tolerance bit NOT NULL,instrument_equivalence varchar(20) NOT NULL,
  status varchar(20) NOT NULL,evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_m1m5_evaluated DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_m1m5_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT UQ_m1m5_evidence UNIQUE(market_id,m1_source,m5_source,bucket_utc)
 );
 IF OBJECT_ID(N'app.instrument_source_mappings',N'U') IS NULL
 CREATE TABLE app.instrument_source_mappings(
  market_id uniqueidentifier NOT NULL,vendor varchar(30) NOT NULL,vendor_symbol varchar(40) NOT NULL,
  instrument_equivalence varchar(20) NOT NULL,price_completeness_preference varchar(20) NOT NULL,
  qualification_allowed bit NOT NULL,evidence_source nvarchar(500) NOT NULL,review_status varchar(20) NOT NULL,
  verified_at_utc datetime2(3) NULL,CONSTRAINT PK_instrument_source_mappings PRIMARY KEY(market_id,vendor),
  CONSTRAINT FK_source_mapping_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id)
 );
 INSERT app.instrument_source_mappings(market_id,vendor,vendor_symbol,instrument_equivalence,price_completeness_preference,qualification_allowed,evidence_source,review_status)
 SELECT market_id,'HISTDATA',CASE WHEN symbol='GERMANY40' THEN 'GRXEUR' ELSE symbol END,
  CASE WHEN symbol='GERMANY40' THEN 'INDEX_REFERENCE' ELSE 'EXACT_PAIR' END,'BID_ASK_FULL',
  CASE WHEN symbol='GERMANY40' THEN 0 ELSE 1 END,'HistData published instrument list and format specification','FORMAT_VERIFIED'
 FROM app.markets WHERE enabled=1 AND research_enabled=1 AND NOT EXISTS(SELECT 1 FROM app.instrument_source_mappings x WHERE x.market_id=app.markets.market_id AND x.vendor='HISTDATA');
 INSERT app.instrument_source_mappings(market_id,vendor,vendor_symbol,instrument_equivalence,price_completeness_preference,qualification_allowed,evidence_source,review_status)
 SELECT market_id,'DUKASCOPY',CASE WHEN symbol='GERMANY40' THEN 'DEUIDXEUR' ELSE symbol END,
  CASE WHEN symbol='GERMANY40' THEN 'INDEX_REFERENCE' ELSE 'UNVERIFIED' END,'BID_ASK_FULL',0,
  'Dukascopy JForex historical-data interface; exact symbol coverage pending controlled adapter probe','COVERAGE_UNVERIFIED'
 FROM app.markets WHERE enabled=1 AND research_enabled=1 AND NOT EXISTS(SELECT 1 FROM app.instrument_source_mappings x WHERE x.market_id=app.markets.market_id AND x.vendor='DUKASCOPY');
 INSERT app.market_candles_m1(market_id,timestamp_utc,source,source_symbol,source_timezone,
  bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,mid_open,mid_high,mid_low,mid_close,
  spread_open,spread_close,spread_min,spread_max,spread_mean,tick_count,price_completeness,quality_state,
  instrument_equivalence,is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible,ingested_at_utc)
 SELECT c.market_id,c.open_time_utc,c.source,m.ig_epic,'UTC',c.bid_open,c.bid_high,c.bid_low,c.bid_close,
  c.ask_open,c.ask_high,c.ask_low,c.ask_close,c.[open],c.high,c.low,c.[close],c.spread_open,c.spread_close,
  c.spread_min,c.spread_max,c.spread_mean,c.tick_count,
  CASE WHEN c.ask_close IS NOT NULL THEN 'BID_ASK_FULL' WHEN c.bid_close IS NOT NULL THEN 'BID_ONLY' ELSE 'MID_ONLY' END,
  CASE WHEN c.quality_status='PASS' THEN 'GOOD' ELSE 'DEGRADED' END,'BROKER_SPECIFIC',0,1,0,1,0,COALESCE(c.ingested_at_utc,c.created_at_utc)
 FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id WHERE c.timeframe='M1'
 AND NOT EXISTS(SELECT 1 FROM app.market_candles_m1 x WHERE x.market_id=c.market_id AND x.timestamp_utc=c.open_time_utc AND x.source=c.source);
 INSERT app.market_candles_m5(market_id,timestamp_utc,source,source_symbol,source_timezone,
  bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,mid_open,mid_high,mid_low,mid_close,
  spread_open,spread_close,spread_min,spread_max,spread_mean,tick_count,price_completeness,quality_state,
  instrument_equivalence,is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible,ingested_at_utc)
 SELECT c.market_id,c.open_time_utc,c.source,m.ig_epic,'UTC',c.bid_open,c.bid_high,c.bid_low,c.bid_close,
  c.ask_open,c.ask_high,c.ask_low,c.ask_close,c.[open],c.high,c.low,c.[close],c.spread_open,c.spread_close,
  c.spread_min,c.spread_max,c.spread_mean,c.tick_count,
  CASE WHEN c.ask_close IS NOT NULL THEN 'BID_ASK_FULL' WHEN c.bid_close IS NOT NULL THEN 'BID_ONLY' ELSE 'MID_ONLY' END,
  CASE WHEN c.quality_status='PASS' THEN 'GOOD' ELSE 'DEGRADED' END,
  CASE WHEN c.source LIKE 'IG_%' THEN 'BROKER_SPECIFIC' ELSE 'UNVERIFIED' END,
  CASE WHEN c.source LIKE 'IG_LIGHTSTREAMER%' THEN 0 ELSE 1 END,
  CASE WHEN c.source LIKE 'IG_LIGHTSTREAMER%' THEN 1 ELSE 0 END,
  CASE WHEN c.source LIKE 'DERIVED_%' THEN 1 ELSE 0 END,1,0,COALESCE(c.ingested_at_utc,c.created_at_utc)
 FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id WHERE c.timeframe='M5'
 AND NOT EXISTS(SELECT 1 FROM app.market_candles_m5 x WHERE x.market_id=c.market_id AND x.timestamp_utc=c.open_time_utc AND x.source=c.source);
 COMMIT TRANSACTION;
 PRINT 'Separate historical M1/M5 evidence foundation and cautious vendor mapping installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO

CREATE OR ALTER TRIGGER app.trg_candles_separate_evidence ON app.candles AFTER INSERT AS
BEGIN
 SET NOCOUNT ON;
 INSERT app.market_candles_m1(market_id,timestamp_utc,source,source_symbol,source_timezone,
  bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,mid_open,mid_high,mid_low,mid_close,
  spread_open,spread_close,spread_min,spread_max,spread_mean,tick_count,price_completeness,quality_state,
  instrument_equivalence,is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible,ingested_at_utc)
 SELECT i.market_id,i.open_time_utc,i.source,m.ig_epic,'UTC',i.bid_open,i.bid_high,i.bid_low,i.bid_close,
  i.ask_open,i.ask_high,i.ask_low,i.ask_close,i.[open],i.high,i.low,i.[close],i.spread_open,i.spread_close,
  i.spread_min,i.spread_max,i.spread_mean,i.tick_count,'BID_ASK_FULL',
  CASE WHEN i.quality_status='PASS' THEN 'GOOD' ELSE 'DEGRADED' END,'BROKER_SPECIFIC',0,1,0,1,0,SYSUTCDATETIME()
 FROM inserted i JOIN app.markets m ON m.market_id=i.market_id WHERE i.timeframe='M1'
 AND NOT EXISTS(SELECT 1 FROM app.market_candles_m1 x WHERE x.market_id=i.market_id AND x.timestamp_utc=i.open_time_utc AND x.source=i.source);
 INSERT app.market_candles_m5(market_id,timestamp_utc,source,source_symbol,source_timezone,
  bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,mid_open,mid_high,mid_low,mid_close,
  spread_open,spread_close,spread_min,spread_max,spread_mean,tick_count,price_completeness,quality_state,
  instrument_equivalence,is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible,ingested_at_utc)
 SELECT i.market_id,i.open_time_utc,i.source,m.ig_epic,'UTC',i.bid_open,i.bid_high,i.bid_low,i.bid_close,
  i.ask_open,i.ask_high,i.ask_low,i.ask_close,i.[open],i.high,i.low,i.[close],i.spread_open,i.spread_close,
  i.spread_min,i.spread_max,i.spread_mean,i.tick_count,
  CASE WHEN i.ask_close IS NOT NULL THEN 'BID_ASK_FULL' WHEN i.bid_close IS NOT NULL THEN 'BID_ONLY' ELSE 'MID_ONLY' END,
  CASE WHEN i.quality_status='PASS' THEN 'GOOD' ELSE 'DEGRADED' END,
  CASE WHEN i.source LIKE 'IG_%' THEN 'BROKER_SPECIFIC' ELSE 'UNVERIFIED' END,
  CASE WHEN i.source LIKE 'IG_LIGHTSTREAMER%' THEN 0 ELSE 1 END,
  CASE WHEN i.source LIKE 'IG_LIGHTSTREAMER%' THEN 1 ELSE 0 END,
  CASE WHEN i.source LIKE 'DERIVED_%' THEN 1 ELSE 0 END,1,0,SYSUTCDATETIME()
 FROM inserted i JOIN app.markets m ON m.market_id=i.market_id WHERE i.timeframe='M5'
 AND NOT EXISTS(SELECT 1 FROM app.market_candles_m5 x WHERE x.market_id=i.market_id AND x.timestamp_utc=i.open_time_utc AND x.source=i.source);
END;
GO
