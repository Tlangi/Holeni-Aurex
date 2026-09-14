USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF COL_LENGTH(N'app.market_candles_m1',N'research_authority') IS NULL
  ALTER TABLE app.market_candles_m1 ADD research_authority varchar(30) NOT NULL
   CONSTRAINT DF_market_m1_research_authority DEFAULT 'RESEARCH_AUTHORITATIVE';
 IF COL_LENGTH(N'app.market_candles_m1',N'execution_authoritative') IS NULL
  ALTER TABLE app.market_candles_m1 ADD execution_authoritative bit NOT NULL
   CONSTRAINT DF_market_m1_execution_authoritative DEFAULT 0;
 IF COL_LENGTH(N'app.market_candles_m5',N'research_authority') IS NULL
  ALTER TABLE app.market_candles_m5 ADD research_authority varchar(30) NOT NULL
   CONSTRAINT DF_market_m5_research_authority DEFAULT 'RESEARCH_AUTHORITATIVE';
 IF COL_LENGTH(N'app.market_candles_m5',N'execution_authoritative') IS NULL
  ALTER TABLE app.market_candles_m5 ADD execution_authoritative bit NOT NULL
   CONSTRAINT DF_market_m5_execution_authoritative DEFAULT 0;
 IF OBJECT_ID(N'app.model_dataset_manifests',N'U') IS NULL
 CREATE TABLE app.model_dataset_manifests(
  manifest_id uniqueidentifier NOT NULL CONSTRAINT PK_model_dataset_manifests PRIMARY KEY,
  market_id uniqueidentifier NOT NULL,model_version_id uniqueidentifier NULL,
  training_start_utc datetime2(3) NOT NULL,training_end_utc datetime2(3) NOT NULL,
  validation_start_utc datetime2(3) NOT NULL,validation_end_utc datetime2(3) NOT NULL,
  holdout_start_utc datetime2(3) NULL,holdout_end_utc datetime2(3) NULL,
  ig_candle_count bigint NOT NULL,dukascopy_repair_count bigint NOT NULL DEFAULT 0,
  proxy_candle_count bigint NOT NULL DEFAULT 0,missing_expected_count bigint NOT NULL DEFAULT 0,
  repair_percentage decimal(9,6) NOT NULL DEFAULT 0,
  consecutiveness_score decimal(9,6) NOT NULL,session_completeness decimal(9,6) NOT NULL,
  dataset_sha256 char(64) NOT NULL,feature_version varchar(80) NOT NULL,
  git_commit varchar(80) NULL,policy_version varchar(80) NOT NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_dataset_manifest_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_dataset_manifest_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id)
 );
 COMMIT TRANSACTION;
 PRINT 'Research authority and immutable dataset manifest schema installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
