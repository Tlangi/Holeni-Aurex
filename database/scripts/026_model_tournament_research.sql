USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_research_retrain_type'
              AND parent_object_id=OBJECT_ID(N'app.research_experiments'))
        ALTER TABLE app.research_experiments DROP CONSTRAINT CK_research_retrain_type;

    ALTER TABLE app.research_experiments ADD CONSTRAINT CK_research_retrain_type
        CHECK(retrain_type IN ('SCHEDULED_RETRAIN','RESEARCH_RETRAIN','DIAGNOSTIC_REPLAY',
                               'HOLDOUT_CANDIDATE','MODEL_TOURNAMENT'));

    COMMIT TRANSACTION;
    PRINT 'Aurex model tournament research migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
