USE [ForexSaas];
GO
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.frozen_research_diagnostic_cohorts',N'U') IS NULL
 CREATE TABLE app.frozen_research_diagnostic_cohorts (
  cohort_id uniqueidentifier NOT NULL CONSTRAINT PK_frozen_research_diagnostic_cohorts PRIMARY KEY,
  market_id uniqueidentifier NOT NULL,
  dataset_sha256 char(64) NOT NULL,
  manifest_sha256 char(64) NOT NULL,
  manifest_json nvarchar(max) NOT NULL,
  authority varchar(40) NOT NULL CONSTRAINT DF_frozen_diagnostic_authority DEFAULT 'NONPROMOTABLE_RESEARCH_ONLY',
  selected_count int NOT NULL,
  valid_ig_outcome_count int NOT NULL,
  frozen_at_utc datetime2(3) NOT NULL CONSTRAINT DF_frozen_diagnostic_frozen DEFAULT SYSUTCDATETIME(),
  CONSTRAINT FK_frozen_diagnostic_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT UQ_frozen_diagnostic_manifest UNIQUE(manifest_sha256),
  CONSTRAINT CK_frozen_diagnostic_json CHECK(ISJSON(manifest_json)=1),
  CONSTRAINT CK_frozen_diagnostic_authority CHECK(authority='NONPROMOTABLE_RESEARCH_ONLY'),
  CONSTRAINT CK_frozen_diagnostic_counts CHECK(selected_count>=0 AND valid_ig_outcome_count>=0 AND valid_ig_outcome_count<=selected_count)
 );
 IF OBJECT_ID(N'app.frozen_research_prediction_outcomes',N'U') IS NULL
 CREATE TABLE app.frozen_research_prediction_outcomes (
  cohort_id uniqueidentifier NOT NULL,
  prediction_id char(64) NOT NULL,
  decision_utc datetime2(3) NOT NULL,
  outcome_status varchar(32) NOT NULL,
  broker_path_available bit NOT NULL,
  outcome_sha256 char(64) NOT NULL,
  outcome_json nvarchar(max) NOT NULL,
  CONSTRAINT PK_frozen_research_prediction_outcomes PRIMARY KEY(cohort_id,prediction_id),
  CONSTRAINT FK_frozen_prediction_cohort FOREIGN KEY(cohort_id) REFERENCES app.frozen_research_diagnostic_cohorts(cohort_id),
  CONSTRAINT CK_frozen_prediction_json CHECK(ISJSON(outcome_json)=1)
 );
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
IF OBJECT_ID(N'app.trg_frozen_research_diagnostic_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_frozen_research_diagnostic_append_only ON app.frozen_research_diagnostic_cohorts AFTER UPDATE, DELETE AS BEGIN THROW 51058, ''Frozen research diagnostic cohorts are append-only'', 1; END');
GO
IF OBJECT_ID(N'app.trg_frozen_research_prediction_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_frozen_research_prediction_append_only ON app.frozen_research_prediction_outcomes AFTER UPDATE, DELETE AS BEGIN THROW 51059, ''Frozen prediction outcomes are append-only'', 1; END');
GO
