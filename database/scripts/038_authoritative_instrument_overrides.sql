USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
  BEGIN TRANSACTION;
  IF OBJECT_ID(N'app.instrument_specification_overrides',N'U') IS NULL
  BEGIN
    CREATE TABLE app.instrument_specification_overrides
    (
      instrument_specification_override_id uniqueidentifier NOT NULL CONSTRAINT PK_instrument_spec_overrides PRIMARY KEY,
      market_id uniqueidentifier NOT NULL,
      version int NOT NULL,
      epic nvarchar(100) NOT NULL,
      minimum_size decimal(19,8) NOT NULL,
      authoritative_size_increment decimal(19,8) NOT NULL,
      minimum_stop_distance decimal(19,8) NOT NULL,
      value_per_point_zar decimal(19,8) NOT NULL,
      margin_factor_pct decimal(9,6) NOT NULL,
      evidence_source nvarchar(500) NOT NULL,
      evidence_sha256 char(64) NOT NULL,
      verified_at_utc datetime2(3) NOT NULL,
      reviewed_by_user_id uniqueidentifier NOT NULL,
      review_acknowledgement varchar(120) NOT NULL,
      revalidate_at_utc datetime2(3) NOT NULL,
      status varchar(20) NOT NULL,
      created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_instrument_override_created DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_instrument_override_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
      CONSTRAINT FK_instrument_override_reviewer FOREIGN KEY(reviewed_by_user_id) REFERENCES app.users(user_id),
      CONSTRAINT UQ_instrument_override_version UNIQUE(market_id,version),
      CONSTRAINT CK_instrument_override_positive CHECK(minimum_size>0 AND authoritative_size_increment>0 AND minimum_stop_distance>0 AND value_per_point_zar>0 AND margin_factor_pct>0),
      CONSTRAINT CK_instrument_override_period CHECK(verified_at_utc<revalidate_at_utc),
      CONSTRAINT CK_instrument_override_status CHECK(status IN ('APPROVED','EXPIRED','REVOKED'))
    );
    CREATE INDEX IX_instrument_override_current ON app.instrument_specification_overrides(market_id,status,revalidate_at_utc DESC);
  END;
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;
GO
