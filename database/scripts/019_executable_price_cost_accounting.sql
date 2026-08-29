USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.replay_trades',N'spread_cost_in_price') IS NULL
        ALTER TABLE app.replay_trades ADD spread_cost_in_price bit NOT NULL
            CONSTRAINT DF_replay_trades_spread_in_price DEFAULT 0;
    IF COL_LENGTH(N'app.replay_trades',N'explicit_transaction_cost_zar') IS NULL
        ALTER TABLE app.replay_trades ADD explicit_transaction_cost_zar decimal(19,4) NOT NULL
            CONSTRAINT DF_replay_trades_explicit_cost DEFAULT 0;
    IF COL_LENGTH(N'app.shadow_trades',N'spread_cost_in_price') IS NULL
        ALTER TABLE app.shadow_trades ADD spread_cost_in_price bit NOT NULL
            CONSTRAINT DF_shadow_trades_spread_in_price DEFAULT 0;

    COMMIT TRANSACTION;
    PRINT 'Added auditable executable-price cost accounting.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
