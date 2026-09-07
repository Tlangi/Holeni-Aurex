USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.forward_evidence_snapshots',N'U') IS NOT NULL
    BEGIN
        IF EXISTS(SELECT 1 FROM sys.check_constraints
                  WHERE parent_object_id=OBJECT_ID(N'app.forward_evidence_snapshots')
                    AND name=N'CK_forward_evidence_state')
            ALTER TABLE app.forward_evidence_snapshots DROP CONSTRAINT CK_forward_evidence_state;

        ALTER TABLE app.forward_evidence_snapshots WITH CHECK ADD CONSTRAINT CK_forward_evidence_state
            CHECK(evidence_state IN ('VALIDATING','RESEARCH_ONLY','ACCUMULATING','BLOCKED',
                                     'FORWARD_SHADOW','DEMO_TEST_READY'));
        ALTER TABLE app.forward_evidence_snapshots CHECK CONSTRAINT CK_forward_evidence_state;
    END;

    COMMIT TRANSACTION;
    PRINT 'Forward evidence states aligned with the governed market lifecycle.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
