USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
  BEGIN TRANSACTION;
  IF COL_LENGTH(N'app.shadow_trades',N'feature_vector_hash') IS NULL
    ALTER TABLE app.shadow_trades ADD feature_vector_hash char(64) NULL;
  IF COL_LENGTH(N'app.shadow_trades',N'feature_version') IS NULL
    ALTER TABLE app.shadow_trades ADD feature_version varchar(100) NULL;
  IF COL_LENGTH(N'app.shadow_trades',N'model_version_id') IS NULL
    ALTER TABLE app.shadow_trades ADD model_version_id uniqueidentifier NULL;
  IF COL_LENGTH(N'app.shadow_trades',N'model_freeze_timestamp_utc') IS NULL
    ALTER TABLE app.shadow_trades ADD model_freeze_timestamp_utc datetime2(3) NULL;
  IF COL_LENGTH(N'app.shadow_trades',N'signal_timestamp_utc') IS NULL
    ALTER TABLE app.shadow_trades ADD signal_timestamp_utc datetime2(3) NULL;
  IF COL_LENGTH(N'app.shadow_trades',N'max_favourable_excursion_zar') IS NULL
    ALTER TABLE app.shadow_trades ADD max_favourable_excursion_zar decimal(19,6) NOT NULL CONSTRAINT DF_shadow_mfe DEFAULT 0;
  IF COL_LENGTH(N'app.shadow_trades',N'max_adverse_excursion_zar') IS NULL
    ALTER TABLE app.shadow_trades ADD max_adverse_excursion_zar decimal(19,6) NOT NULL CONSTRAINT DF_shadow_mae DEFAULT 0;
  IF COL_LENGTH(N'app.shadow_trades',N'net_r_multiple') IS NULL
    ALTER TABLE app.shadow_trades ADD net_r_multiple decimal(19,8) NULL;
  IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_shadow_model_version')
    ALTER TABLE app.shadow_trades ADD CONSTRAINT FK_shadow_model_version FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id);
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;
GO
