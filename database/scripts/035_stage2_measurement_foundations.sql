USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
  BEGIN TRANSACTION;
  IF OBJECT_ID(N'app.market_qualification_snapshots',N'U') IS NULL
  BEGIN
    CREATE TABLE app.market_qualification_snapshots
    (
      market_qualification_snapshot_id uniqueidentifier NOT NULL CONSTRAINT PK_market_qualification_snapshots PRIMARY KEY,
      market_id uniqueidentifier NOT NULL,
      recent_feed_status varchar(20) NOT NULL,
      m5_freshness varchar(30) NOT NULL,
      m15_freshness varchar(30) NOT NULL,
      recent_gap_count int NOT NULL,
      historical_gap_count int NOT NULL,
      historical_session_completeness decimal(12,8) NOT NULL,
      duplicate_count int NOT NULL,
      invalid_ohlc_count int NOT NULL,
      provider_boundary_count int NOT NULL,
      realtime_ready bit NOT NULL,
      research_ready bit NOT NULL,
      training_eligible bit NOT NULL,
      shadow_trading_eligible bit NOT NULL,
      execution_eligible bit NOT NULL,
      qualification_reason nvarchar(500) NOT NULL,
      evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_qualification_evaluated DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_market_qualification_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
      CONSTRAINT CK_market_qualification_completeness CHECK(historical_session_completeness BETWEEN 0 AND 1)
    );
    CREATE INDEX IX_market_qualification_market_time ON app.market_qualification_snapshots(market_id,evaluated_at_utc DESC);
  END;
  IF OBJECT_ID(N'app.broker_working_orders',N'U') IS NULL
  BEGIN
    CREATE TABLE app.broker_working_orders
    (
      broker_working_order_id uniqueidentifier NOT NULL CONSTRAINT PK_broker_working_orders PRIMARY KEY,
      tenant_id uniqueidentifier NOT NULL,
      trading_account_id uniqueidentifier NOT NULL,
      broker_deal_id varchar(100) NOT NULL,
      deal_reference varchar(100) NULL,
      epic varchar(100) NULL,
      direction varchar(10) NULL,
      size decimal(19,8) NULL,
      level decimal(19,8) NULL,
      status varchar(30) NOT NULL,
      first_seen_at_utc datetime2(3) NOT NULL CONSTRAINT DF_working_order_first_seen DEFAULT SYSUTCDATETIME(),
      last_seen_at_utc datetime2(3) NOT NULL CONSTRAINT DF_working_order_last_seen DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_working_order_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
      CONSTRAINT FK_working_order_account FOREIGN KEY(trading_account_id) REFERENCES app.trading_accounts(trading_account_id),
      CONSTRAINT UQ_working_order_account_deal UNIQUE(trading_account_id,broker_deal_id)
    );
  END;
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;
GO
