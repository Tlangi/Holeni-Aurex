USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;

 IF OBJECT_ID(N'app.trading_agent_runs',N'U') IS NULL
 BEGIN
  CREATE TABLE app.trading_agent_runs(
   run_id uniqueidentifier NOT NULL CONSTRAINT PK_trading_agent_runs PRIMARY KEY,
   tenant_id uniqueidentifier NOT NULL, market_id uniqueidentifier NOT NULL,
   decision_time_utc datetime2(3) NOT NULL, data_cutoff_utc datetime2(3) NOT NULL,
   horizon_minutes int NOT NULL, input_snapshot_sha256 char(64) NOT NULL,
   provider varchar(32) NOT NULL, local_model nvarchar(160) NOT NULL,
   tradingagents_version varchar(40) NOT NULL, tradingagents_commit char(40) NOT NULL,
   prompt_version varchar(80) NOT NULL, status varchar(32) NOT NULL,
   latency_ms int NULL, error_code varchar(80) NULL,
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_trading_agent_runs_created DEFAULT SYSUTCDATETIME(),
   completed_at_utc datetime2(3) NULL,
   CONSTRAINT FK_trading_agent_runs_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
   CONSTRAINT FK_trading_agent_runs_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT CK_trading_agent_runs_cutoff CHECK(data_cutoff_utc<=decision_time_utc),
   CONSTRAINT CK_trading_agent_runs_provider CHECK(provider IN ('LOCAL_OLLAMA','LOCAL_OPENAI_COMPATIBLE')),
   CONSTRAINT CK_trading_agent_runs_status CHECK(status IN
    ('QUEUED','RUNNING','SUCCEEDED','DEGRADED','LOCAL_LLM_UNAVAILABLE','MODEL_NOT_LOADED','CIRCUIT_OPEN','FAILED')),
   CONSTRAINT CK_trading_agent_runs_hash CHECK(input_snapshot_sha256 NOT LIKE '%[^0-9a-f]%'),
   CONSTRAINT CK_trading_agent_runs_commit CHECK(tradingagents_commit NOT LIKE '%[^0-9a-f]%')
  );
  CREATE UNIQUE INDEX UX_trading_agent_runs_snapshot ON app.trading_agent_runs
   (tenant_id,market_id,data_cutoff_utc,horizon_minutes,input_snapshot_sha256,
    local_model,tradingagents_commit,prompt_version);
  CREATE INDEX IX_trading_agent_runs_queue ON app.trading_agent_runs(status,created_at_utc);
 END;

 IF OBJECT_ID(N'app.trading_agent_decisions',N'U') IS NULL
 BEGIN
  CREATE TABLE app.trading_agent_decisions(
   trading_agent_decision_id uniqueidentifier NOT NULL CONSTRAINT PK_trading_agent_decisions PRIMARY KEY,
   run_id uniqueidentifier NOT NULL, role varchar(60) NOT NULL,
   direction varchar(10) NOT NULL, confidence decimal(7,6) NOT NULL,
   regime varchar(40) NOT NULL, reasoning_summary nvarchar(2000) NOT NULL,
   supporting_factors_json nvarchar(max) NOT NULL, opposing_factors_json nvarchar(max) NOT NULL,
   risk_flags_json nvarchar(max) NOT NULL, feature_suggestions_json nvarchar(max) NOT NULL,
   model_critique_json nvarchar(max) NOT NULL, evidence_quality varchar(32) NOT NULL,
   audit_status varchar(10) NOT NULL, result_sha256 char(64) NOT NULL,
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_trading_agent_decisions_created DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_trading_agent_decisions_run FOREIGN KEY(run_id) REFERENCES app.trading_agent_runs(run_id),
   CONSTRAINT CK_trading_agent_decisions_direction CHECK(direction IN ('LONG','SHORT','NEUTRAL','REJECT')),
   CONSTRAINT CK_trading_agent_decisions_confidence CHECK(confidence BETWEEN 0 AND 1),
   CONSTRAINT CK_trading_agent_decisions_quality CHECK(evidence_quality IN
    ('POINT_IN_TIME_VERIFIED','RESEARCH_ONLY_UNVERIFIED','INSUFFICIENT')),
   CONSTRAINT CK_trading_agent_decisions_audit CHECK(audit_status IN ('PASS','FAIL','PENDING')),
   CONSTRAINT CK_trading_agent_decisions_fail_closed CHECK(
    (audit_status='PASS' AND evidence_quality='POINT_IN_TIME_VERIFIED') OR direction IN ('NEUTRAL','REJECT')),
   CONSTRAINT CK_trading_agent_decisions_json CHECK(
    ISJSON(supporting_factors_json)=1 AND ISJSON(opposing_factors_json)=1 AND
    ISJSON(risk_flags_json)=1 AND ISJSON(feature_suggestions_json)=1 AND ISJSON(model_critique_json)=1)
  );
 END;

 IF OBJECT_ID(N'app.trading_agent_evaluations',N'U') IS NULL
 BEGIN
  CREATE TABLE app.trading_agent_evaluations(
   evaluation_id uniqueidentifier NOT NULL CONSTRAINT PK_trading_agent_evaluations PRIMARY KEY,
   run_id uniqueidentifier NOT NULL, resolved_at_utc datetime2(3) NOT NULL,
   actual_direction varchar(10) NOT NULL, gross_return decimal(19,10) NULL,
   net_return decimal(19,10) NULL, mfe_points decimal(19,8) NULL, mae_points decimal(19,8) NULL,
   cost_points decimal(19,8) NULL, aurex_model_correct bit NULL,
   tradingagents_correct bit NULL, agreement_state varchar(32) NOT NULL,
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_trading_agent_evaluations_created DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_trading_agent_evaluations_run FOREIGN KEY(run_id) REFERENCES app.trading_agent_runs(run_id),
   CONSTRAINT UX_trading_agent_evaluations_run UNIQUE(run_id),
   CONSTRAINT CK_trading_agent_evaluations_direction CHECK(actual_direction IN ('LONG','SHORT','FLAT')),
   CONSTRAINT CK_trading_agent_evaluations_agreement CHECK(agreement_state IN
    ('AGREE','DISAGREE','NEUTRAL','REJECTED','NOT_COMPARABLE'))
  );
 END;

 IF OBJECT_ID(N'app.trading_agent_feature_hypotheses',N'U') IS NULL
 BEGIN
  CREATE TABLE app.trading_agent_feature_hypotheses(
   hypothesis_id uniqueidentifier NOT NULL CONSTRAINT PK_trading_agent_feature_hypotheses PRIMARY KEY,
   run_id uniqueidentifier NOT NULL, hypothesis nvarchar(1000) NOT NULL,
   required_data_json nvarchar(max) NOT NULL, expected_behaviour nvarchar(1000) NOT NULL,
   leakage_risk nvarchar(1000) NOT NULL, review_status varchar(20) NOT NULL CONSTRAINT DF_tafh_review DEFAULT 'PENDING',
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_tafh_created DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_tafh_run FOREIGN KEY(run_id) REFERENCES app.trading_agent_runs(run_id),
   CONSTRAINT CK_tafh_json CHECK(ISJSON(required_data_json)=1),
   CONSTRAINT CK_tafh_review CHECK(review_status IN ('PENDING','APPROVED_FOR_EXPERIMENT','REJECTED','TESTED'))
  );
 END;

 COMMIT TRANSACTION;
 PRINT 'TradingAgents research provenance installed; no broker or promotion authority granted.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
