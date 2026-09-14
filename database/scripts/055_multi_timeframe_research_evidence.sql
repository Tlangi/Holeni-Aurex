USE [ForexSaas];
GO
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.multi_timeframe_research_experiments',N'U') IS NULL
 CREATE TABLE app.multi_timeframe_research_experiments (
  experiment_id uniqueidentifier NOT NULL CONSTRAINT PK_multi_timeframe_research_experiments PRIMARY KEY,
  market_id uniqueidentifier NOT NULL,
  research_lineage_id uniqueidentifier NOT NULL,
  hypothesis nvarchar(1000) NOT NULL,
  architecture_json nvarchar(max) NOT NULL,
  policy_json nvarchar(max) NOT NULL,
  dataset_sha256 char(64) NOT NULL,
  source_identity varchar(100) NOT NULL,
  decision varchar(30) NOT NULL,
  development_start_utc datetime2(3) NOT NULL,
  development_end_utc datetime2(3) NOT NULL,
  holdout_start_utc datetime2(3) NOT NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_multitimeframe_experiment_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_multitimeframe_experiment_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT FK_multitimeframe_experiment_lineage FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id),
  CONSTRAINT CK_multitimeframe_experiment_json CHECK (ISJSON(architecture_json)=1 AND ISJSON(policy_json)=1),
  CONSTRAINT CK_multitimeframe_experiment_period CHECK (development_start_utc < development_end_utc AND development_end_utc < holdout_start_utc),
  CONSTRAINT CK_multitimeframe_experiment_decision CHECK (decision IN ('REJECTED','PROMISING','FROZEN_FOR_HOLDOUT','DEMO_EXPERIMENT_ELIGIBLE','SUPERSEDED'))
 );
 IF OBJECT_ID(N'app.research_prediction_trade_results',N'U') IS NULL
 CREATE TABLE app.research_prediction_trade_results (
  result_id uniqueidentifier NOT NULL CONSTRAINT PK_research_prediction_trade_results PRIMARY KEY,
  experiment_id uniqueidentifier NOT NULL,
  prediction_timestamp_utc datetime2(3) NOT NULL,
  fold_id int NOT NULL,
  dataset_row_id varchar(100) NOT NULL,
  model_version varchar(100) NOT NULL,
  probability float NOT NULL,
  predicted_direction varchar(10) NOT NULL,
  actual_label varchar(20) NULL,
  outcome_json nvarchar(max) NOT NULL,
  outcome_sha256 char(64) NOT NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_prediction_trade_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_research_prediction_trade_experiment FOREIGN KEY(experiment_id) REFERENCES app.multi_timeframe_research_experiments(experiment_id),
  CONSTRAINT UQ_research_prediction_trade_cohort UNIQUE(experiment_id,prediction_timestamp_utc,fold_id,dataset_row_id),
  CONSTRAINT CK_research_prediction_trade_probability CHECK(probability>=0 AND probability<=1),
  CONSTRAINT CK_research_prediction_trade_direction CHECK(predicted_direction IN ('LONG','SHORT','NO_TRADE')),
  CONSTRAINT CK_research_prediction_trade_outcome_json CHECK(ISJSON(outcome_json)=1)
 );
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
IF OBJECT_ID(N'app.trg_multitimeframe_experiments_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_multitimeframe_experiments_append_only ON app.multi_timeframe_research_experiments AFTER UPDATE, DELETE AS BEGIN THROW 51055, ''Research experiments are append-only'', 1; END');
GO
IF OBJECT_ID(N'app.trg_research_prediction_trade_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_research_prediction_trade_append_only ON app.research_prediction_trade_results AFTER UPDATE, DELETE AS BEGIN THROW 51056, ''Research prediction/trade evidence is append-only'', 1; END');
GO
