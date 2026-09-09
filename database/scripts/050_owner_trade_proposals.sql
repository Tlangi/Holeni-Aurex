USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.trade_proposals',N'U') IS NULL
 BEGIN
  CREATE TABLE app.trade_proposals(
   trade_proposal_id uniqueidentifier NOT NULL CONSTRAINT PK_trade_proposals PRIMARY KEY,
   tenant_id uniqueidentifier NOT NULL, market_id uniqueidentifier NOT NULL,
   trading_agent_run_id uniqueidentifier NULL, model_version_id uniqueidentifier NULL,
   direction varchar(4) NOT NULL, confidence decimal(7,6) NOT NULL,
   proposed_size decimal(19,8) NOT NULL, entry_price decimal(19,8) NOT NULL,
   stop_price decimal(19,8) NOT NULL, target_price decimal(19,8) NOT NULL,
   risk_zar decimal(19,6) NOT NULL, horizon_minutes int NOT NULL,
   decision_time_utc datetime2(3) NOT NULL, data_cutoff_utc datetime2(3) NOT NULL,
   expires_at_utc datetime2(3) NOT NULL, status varchar(32) NOT NULL,
   rationale_summary nvarchar(2000) NOT NULL, evidence_json nvarchar(max) NOT NULL,
   input_snapshot_sha256 char(64) NOT NULL, proposal_sha256 char(64) NOT NULL,
   notification_status varchar(24) NOT NULL CONSTRAINT DF_trade_proposals_notification DEFAULT 'PENDING',
   notification_error_code varchar(80) NULL,
   decided_by_user_id uniqueidentifier NULL, decided_at_utc datetime2(3) NULL,
   decision_reason nvarchar(500) NULL,
   created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_trade_proposals_created DEFAULT SYSUTCDATETIME(),
   updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_trade_proposals_updated DEFAULT SYSUTCDATETIME(),
   CONSTRAINT FK_trade_proposals_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
   CONSTRAINT FK_trade_proposals_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
   CONSTRAINT FK_trade_proposals_agent_run FOREIGN KEY(trading_agent_run_id) REFERENCES app.trading_agent_runs(run_id),
   CONSTRAINT FK_trade_proposals_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
   CONSTRAINT FK_trade_proposals_decider FOREIGN KEY(decided_by_user_id) REFERENCES app.users(user_id),
   CONSTRAINT CK_trade_proposals_direction CHECK(direction IN ('BUY','SELL')),
   CONSTRAINT CK_trade_proposals_confidence CHECK(confidence BETWEEN 0 AND 1),
   CONSTRAINT CK_trade_proposals_numbers CHECK(proposed_size>0 AND entry_price>0 AND stop_price>0
    AND target_price>0 AND risk_zar>0 AND horizon_minutes BETWEEN 1 AND 10080),
   CONSTRAINT CK_trade_proposals_levels CHECK(
    (direction='BUY' AND stop_price<entry_price AND target_price>entry_price) OR
    (direction='SELL' AND stop_price>entry_price AND target_price<entry_price)),
   CONSTRAINT CK_trade_proposals_time CHECK(data_cutoff_utc<=decision_time_utc AND expires_at_utc>decision_time_utc),
   CONSTRAINT CK_trade_proposals_status CHECK(status IN
    ('PENDING_OWNER','OWNER_APPROVED_FOR_RISK','OWNER_DECLINED','EXPIRED','CANCELLED','RISK_REJECTED','CONSUMED')),
   CONSTRAINT CK_trade_proposals_notification CHECK(notification_status IN ('PENDING','SENT','FAILED','NOT_CONFIGURED')),
   CONSTRAINT CK_trade_proposals_decision CHECK(
    (status='PENDING_OWNER' AND decided_by_user_id IS NULL AND decided_at_utc IS NULL) OR
    (status<>'PENDING_OWNER')),
   CONSTRAINT CK_trade_proposals_json CHECK(ISJSON(evidence_json)=1)
  );
  CREATE UNIQUE INDEX UX_trade_proposals_digest ON app.trade_proposals(tenant_id,proposal_sha256);
  CREATE INDEX IX_trade_proposals_owner_queue ON app.trade_proposals(tenant_id,status,expires_at_utc,created_at_utc DESC);
 END;
 COMMIT TRANSACTION;
 PRINT 'Owner trade proposal queue installed; approval is not broker submission.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
