USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.model_versions', N'demo_experiment_eligible') IS NULL
    BEGIN
        ALTER TABLE app.model_versions ADD demo_experiment_eligible bit NOT NULL
            CONSTRAINT DF_model_versions_demo_experiment_eligible DEFAULT 0;
    END;

    IF COL_LENGTH(N'app.trade_proposals', N'execution_mode') IS NULL
    BEGIN
        ALTER TABLE app.trade_proposals ADD execution_mode varchar(32) NOT NULL
            CONSTRAINT DF_trade_proposals_execution_mode DEFAULT 'HUMAN_APPROVED_DEMO';
        ALTER TABLE app.trade_proposals ADD approved_bid decimal(19,8) NULL,
            approved_ask decimal(19,8) NULL,
            approved_spread decimal(19,8) NULL,
            approval_expires_at_utc datetime2(3) NULL,
            market_revalidation_status varchar(40) NULL;
    END;

    COMMIT TRANSACTION;
    PRINT 'Human-approved Demo eligibility is explicit and disabled by default.';
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name=N'CK_trade_proposals_execution_mode')
    ALTER TABLE app.trade_proposals ADD CONSTRAINT CK_trade_proposals_execution_mode
        CHECK (execution_mode IN ('HUMAN_APPROVED_DEMO'));
GO
