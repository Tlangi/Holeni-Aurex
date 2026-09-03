USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
  BEGIN TRANSACTION;

  IF COL_LENGTH(N'app.auth_sessions',N'csrf_token_hash') IS NULL
    ALTER TABLE app.auth_sessions ADD csrf_token_hash binary(32) NULL;

  IF COL_LENGTH(N'app.broker_market_rules',N'size_increment_source') IS NULL
    ALTER TABLE app.broker_market_rules ADD size_increment_source varchar(40) NULL;
  IF COL_LENGTH(N'app.broker_market_rules',N'size_increment_authoritative') IS NULL
    ALTER TABLE app.broker_market_rules ADD size_increment_authoritative bit NOT NULL
      CONSTRAINT DF_broker_rule_increment_authoritative DEFAULT 0;
  IF COL_LENGTH(N'app.broker_market_rules',N'raw_rule_sha256') IS NULL
    ALTER TABLE app.broker_market_rules ADD raw_rule_sha256 char(64) NULL;

  IF OBJECT_ID(N'app.shadow_candidates',N'U') IS NULL
  BEGIN
    CREATE TABLE app.shadow_candidates
    (
      shadow_candidate_id uniqueidentifier NOT NULL CONSTRAINT PK_shadow_candidates PRIMARY KEY,
      tenant_id uniqueidentifier NOT NULL,
      market_id uniqueidentifier NOT NULL,
      signal_id uniqueidentifier NULL,
      model_version_id uniqueidentifier NULL,
      candle_id bigint NULL,
      direction varchar(4) NOT NULL,
      decision varchar(20) NOT NULL,
      rejection_reason varchar(100) NULL,
      feature_vector_hash char(64) NOT NULL,
      feature_version varchar(100) NOT NULL,
      model_freeze_timestamp_utc datetime2(3) NOT NULL,
      signal_timestamp_utc datetime2(3) NOT NULL,
      account_equity decimal(19,6) NULL,
      risk_percentage decimal(9,6) NULL,
      maximum_permitted_loss decimal(19,6) NULL,
      raw_size decimal(19,8) NULL,
      broker_rounded_size decimal(19,8) NULL,
      estimated_stop_loss decimal(19,6) NULL,
      estimated_margin decimal(19,6) NULL,
      effective_risk_percentage decimal(9,6) NULL,
      entry_price decimal(19,8) NULL,
      stop_price decimal(19,8) NULL,
      target_price decimal(19,8) NULL,
      estimated_cost_zar decimal(19,6) NULL,
      calculation_json nvarchar(max) NOT NULL,
      created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_shadow_candidates_created DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_shadow_candidates_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
      CONSTRAINT FK_shadow_candidates_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
      CONSTRAINT FK_shadow_candidates_signal FOREIGN KEY(signal_id) REFERENCES app.signals(signal_id),
      CONSTRAINT FK_shadow_candidates_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
      CONSTRAINT FK_shadow_candidates_candle FOREIGN KEY(candle_id) REFERENCES app.candles(candle_id),
      CONSTRAINT CK_shadow_candidates_direction CHECK(direction IN ('BUY','SELL')),
      CONSTRAINT CK_shadow_candidates_decision CHECK(decision IN ('APPROVED','REJECTED')),
      CONSTRAINT CK_shadow_candidates_json CHECK(ISJSON(calculation_json)=1)
    );
    CREATE INDEX IX_shadow_candidates_tenant_time ON app.shadow_candidates(tenant_id,created_at_utc DESC);
  END;

  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;
GO
