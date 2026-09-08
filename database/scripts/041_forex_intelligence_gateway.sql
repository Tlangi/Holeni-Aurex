USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.agent_decisions',N'U') IS NULL
 BEGIN
  CREATE TABLE app.agent_decisions(
   agent_decision_id uniqueidentifier NOT NULL CONSTRAINT PK_agent_decisions PRIMARY KEY,
   tenant_id uniqueidentifier NOT NULL, correlation_id uniqueidentifier NOT NULL,
   market_id uniqueidentifier NOT NULL, agent_role varchar(40) NOT NULL,
   direction varchar(10) NOT NULL, confidence decimal(7,6) NOT NULL,
   expected_horizon_minutes int NOT NULL, expected_move_points decimal(19,8) NULL,
   reasoning_summary nvarchar(2000) NOT NULL, supporting_factors_json nvarchar(max) NOT NULL,
   opposing_factors_json nvarchar(max) NOT NULL, risk_flags_json nvarchar(max) NOT NULL,
   macro_snapshot_id uniqueidentifier NULL, market_snapshot_id uniqueidentifier NOT NULL,
   news_snapshot_id uniqueidentifier NULL, provider varchar(40) NOT NULL,
   model_name nvarchar(160) NOT NULL, model_version nvarchar(160) NULL,
   prompt_version varchar(80) NOT NULL, requested_analysis_utc datetime2(3) NOT NULL,
   market_data_cutoff_utc datetime2(3) NOT NULL, macro_data_cutoff_utc datetime2(3) NULL,
   news_data_cutoff_utc datetime2(3) NULL,
   analysis_timestamp_utc datetime2(3) NOT NULL CONSTRAINT DF_agent_decisions_analysis DEFAULT SYSUTCDATETIME(),
   latency_ms int NULL, input_tokens int NULL, output_tokens int NULL,
   estimated_cost_usd decimal(19,8) NULL, evidence_quality varchar(32) NOT NULL,
   audit_status varchar(10) NOT NULL, provenance_json nvarchar(max) NOT NULL,
   provenance_sha256 char(64) NOT NULL,
   CONSTRAINT FK_agent_decisions_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
   CONSTRAINT FK_agent_decisions_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT CK_agent_decisions_direction CHECK(direction IN ('LONG','SHORT','NEUTRAL','REJECT')),
   CONSTRAINT CK_agent_decisions_confidence CHECK(confidence BETWEEN 0 AND 1),
   CONSTRAINT CK_agent_decisions_quality CHECK(evidence_quality IN ('POINT_IN_TIME_VERIFIED','RESEARCH_ONLY_UNVERIFIED','INSUFFICIENT')),
   CONSTRAINT CK_agent_decisions_audit CHECK(audit_status IN ('PASS','FAIL','PENDING')),
   CONSTRAINT CK_agent_decisions_cutoff CHECK(market_data_cutoff_utc<=requested_analysis_utc
    AND (macro_data_cutoff_utc IS NULL OR macro_data_cutoff_utc<=requested_analysis_utc)
    AND (news_data_cutoff_utc IS NULL OR news_data_cutoff_utc<=requested_analysis_utc)),
   CONSTRAINT CK_agent_decisions_fail_closed CHECK((audit_status='PASS' AND evidence_quality='POINT_IN_TIME_VERIFIED')
    OR direction IN ('NEUTRAL','REJECT')),
   CONSTRAINT CK_agent_decisions_json CHECK(ISJSON(supporting_factors_json)=1 AND ISJSON(opposing_factors_json)=1
    AND ISJSON(risk_flags_json)=1 AND ISJSON(provenance_json)=1)
  );
  CREATE INDEX IX_agent_decisions_leaderboard ON app.agent_decisions
   (tenant_id,market_id,agent_role,analysis_timestamp_utc DESC)
   INCLUDE(direction,confidence,provider,model_name,evidence_quality,audit_status);
  CREATE UNIQUE INDEX UX_agent_decisions_provenance ON app.agent_decisions
   (tenant_id,correlation_id,agent_role,provenance_sha256);
 END;
 COMMIT TRANSACTION;
 PRINT 'Forex intelligence evidence boundary installed; no execution permission granted.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
