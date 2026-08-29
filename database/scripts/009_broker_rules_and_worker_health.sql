USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.broker_market_rules', N'stop_distance_unit') IS NULL
        ALTER TABLE app.broker_market_rules ADD stop_distance_unit varchar(20) NULL;
    IF COL_LENGTH(N'app.broker_market_rules', N'lot_size') IS NULL
        ALTER TABLE app.broker_market_rules ADD lot_size decimal(19,8) NULL;
    IF COL_LENGTH(N'app.broker_market_rules', N'market_status') IS NULL
        ALTER TABLE app.broker_market_rules ADD market_status varchar(30) NULL;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
