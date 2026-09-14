USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF COL_LENGTH(N'app.model_versions',N'dataset_sha256') IS NULL
  ALTER TABLE app.model_versions ADD dataset_sha256 char(64) NULL;
 IF COL_LENGTH(N'app.model_versions',N'dataset_rows') IS NULL
  ALTER TABLE app.model_versions ADD dataset_rows bigint NULL;
 IF COL_LENGTH(N'app.model_versions',N'dataset_end_utc') IS NULL
  ALTER TABLE app.model_versions ADD dataset_end_utc datetime2(3) NULL;
 IF COL_LENGTH(N'app.model_evaluations',N'gate_evidence_json') IS NULL
  ALTER TABLE app.model_evaluations ADD gate_evidence_json nvarchar(max) NULL;
 IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_model_evaluations_gate_json')
  EXEC(N'ALTER TABLE app.model_evaluations ADD CONSTRAINT CK_model_evaluations_gate_json
   CHECK(gate_evidence_json IS NULL OR ISJSON(gate_evidence_json)=1)');
 COMMIT TRANSACTION;
 PRINT 'Model dataset identity and shadow-blocker visibility schema installed.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
