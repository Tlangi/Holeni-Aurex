USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF COL_LENGTH(N'app.signals',N'market_decision_id') IS NULL
    EXEC(N'ALTER TABLE app.signals ADD market_decision_id uniqueidentifier NULL;');
GO

BEGIN TRY
    BEGIN TRANSACTION;

    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_signals_market_decision')
        ALTER TABLE app.signals ADD CONSTRAINT FK_signals_market_decision
            FOREIGN KEY(market_decision_id) REFERENCES app.market_decisions(market_decision_id);

    IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'app.signals') AND name=N'IX_signals_market_decision')
        CREATE INDEX IX_signals_market_decision ON app.signals(market_decision_id) WHERE market_decision_id IS NOT NULL;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
