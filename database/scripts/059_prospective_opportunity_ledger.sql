USE [ForexSaas];
GO
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID(N'app.prospective_opportunity_events',N'U') IS NULL
 CREATE TABLE app.prospective_opportunity_events (
  event_id uniqueidentifier NOT NULL CONSTRAINT PK_prospective_opportunity_events PRIMARY KEY,
  transition_key char(64) NOT NULL,
  opportunity_id char(64) NOT NULL,
  market_id uniqueidentifier NOT NULL,
  m15_candle_id bigint NOT NULL,
  join_version varchar(80) NOT NULL,
  transition_status varchar(32) NOT NULL,
  transition_reason varchar(100) NOT NULL,
  atr_snapshot_sha256 char(64) NULL,
  feature_snapshot_sha256 char(64) NULL,
  ig_m1_path_sha256 char(64) NULL,
  evidence_sha256 char(64) NOT NULL,
  evidence_json nvarchar(max) NOT NULL,
  observed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_prospective_event_observed DEFAULT SYSUTCDATETIME(),
  CONSTRAINT UQ_prospective_transition UNIQUE(transition_key),
  CONSTRAINT FK_prospective_event_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
  CONSTRAINT FK_prospective_event_candle FOREIGN KEY(m15_candle_id) REFERENCES app.candles(candle_id),
  CONSTRAINT CK_prospective_event_status CHECK(transition_status IN
   ('ATR_PENDING','FEATURE_PENDING','ROLLOVER_BLOCKED','PATH_PENDING','PATH_BLOCKED','JOINED')),
  CONSTRAINT CK_prospective_event_json CHECK(ISJSON(evidence_json)=1)
 );
 IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'app.prospective_opportunity_events') AND name=N'IX_prospective_event_market_status')
  CREATE INDEX IX_prospective_event_market_status ON app.prospective_opportunity_events(market_id,transition_status,observed_at_utc)
   INCLUDE(opportunity_id,evidence_sha256);

 IF OBJECT_ID(N'app.prospective_accumulation_milestones',N'U') IS NULL
 CREATE TABLE app.prospective_accumulation_milestones (
  milestone_id uniqueidentifier NOT NULL CONSTRAINT PK_prospective_accumulation_milestones PRIMARY KEY,
  snapshot_sha256 char(64) NOT NULL,
  artifact_path nvarchar(500) NOT NULL,
  joined_counts_json nvarchar(max) NOT NULL,
  market_target_reached bit NOT NULL,
  created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_prospective_milestone_created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT UQ_prospective_milestone_snapshot UNIQUE(snapshot_sha256),
  CONSTRAINT UQ_prospective_milestone_path UNIQUE(artifact_path),
  CONSTRAINT CK_prospective_milestone_json CHECK(ISJSON(joined_counts_json)=1)
 );
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
IF OBJECT_ID(N'app.trg_prospective_events_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_prospective_events_append_only ON app.prospective_opportunity_events AFTER UPDATE, DELETE AS BEGIN THROW 51060, ''Prospective opportunity events are append-only'', 1; END');
GO
IF OBJECT_ID(N'app.trg_prospective_milestones_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_prospective_milestones_append_only ON app.prospective_accumulation_milestones AFTER UPDATE, DELETE AS BEGIN THROW 51061, ''Prospective accumulation milestones are append-only'', 1; END');
GO
CREATE OR ALTER VIEW app.vw_prospective_training_gate AS
SELECT m.market_id,m.symbol,
 COUNT(DISTINCT CASE WHEN e.transition_status='JOINED' THEN e.opportunity_id END) joined_opportunities,
 CAST(CASE WHEN COUNT(DISTINCT CASE WHEN e.transition_status='JOINED' THEN e.opportunity_id END)>=30 THEN 1 ELSE 0 END AS bit) training_gate_open
FROM app.markets m
LEFT JOIN app.prospective_opportunity_events e ON e.market_id=m.market_id
WHERE m.enabled=1
GROUP BY m.market_id,m.symbol;
GO
