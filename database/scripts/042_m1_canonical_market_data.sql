USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(N'app.candles') AND name=N'CK_candles_timeframe')
  ALTER TABLE app.candles DROP CONSTRAINT CK_candles_timeframe;
 ALTER TABLE app.candles WITH CHECK ADD CONSTRAINT CK_candles_timeframe
  CHECK(timeframe IN ('M1','M5','M15','M30','H1','H4','D1'));
 ALTER TABLE app.candles CHECK CONSTRAINT CK_candles_timeframe;
 IF COL_LENGTH(N'app.candles',N'spread_min') IS NULL ALTER TABLE app.candles ADD spread_min decimal(19,8) NULL;
 IF COL_LENGTH(N'app.candles',N'spread_max') IS NULL ALTER TABLE app.candles ADD spread_max decimal(19,8) NULL;
 IF COL_LENGTH(N'app.candles',N'spread_mean') IS NULL ALTER TABLE app.candles ADD spread_mean decimal(19,8) NULL;
 IF COL_LENGTH(N'app.candles',N'ingested_at_utc') IS NULL ALTER TABLE app.candles ADD ingested_at_utc datetime2(3) NULL;
 IF COL_LENGTH(N'app.candles',N'gap_status') IS NULL ALTER TABLE app.candles ADD gap_status varchar(20) NULL;
 IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(N'app.live_candle_snapshots') AND name=N'CK_live_candle_timeframe')
  ALTER TABLE app.live_candle_snapshots DROP CONSTRAINT CK_live_candle_timeframe;
 ALTER TABLE app.live_candle_snapshots WITH CHECK ADD CONSTRAINT CK_live_candle_timeframe
  CHECK(timeframe IN ('M1','M5','M15','M30','H1','H4','D1'));
 ALTER TABLE app.live_candle_snapshots CHECK CONSTRAINT CK_live_candle_timeframe;
 IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(N'app.market_data_quality_runs') AND name=N'CK_quality_runs_timeframe')
  ALTER TABLE app.market_data_quality_runs DROP CONSTRAINT CK_quality_runs_timeframe;
 ALTER TABLE app.market_data_quality_runs WITH CHECK ADD CONSTRAINT CK_quality_runs_timeframe
  CHECK(timeframe IN ('M1','M5','M15','M30','H1','H4','D1'));
 ALTER TABLE app.market_data_quality_runs CHECK CONSTRAINT CK_quality_runs_timeframe;
 CREATE INDEX IX_candles_m1_continuity ON app.candles(market_id,open_time_utc DESC)
  INCLUDE(bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,spread_close,quality_status,gap_status)
  WHERE timeframe='M1' AND completed=1;
 COMMIT TRANSACTION;
 PRINT 'Canonical M1 storage enabled for all configured research markets.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
