USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.market_seed_state', N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_seed_state
        (
            market_id uniqueidentifier NOT NULL CONSTRAINT PK_market_seed_state PRIMARY KEY,
            target_m15_candles int NOT NULL,
            last_attempt_at_utc datetime2(3) NULL,
            last_result varchar(40) NULL,
            last_error_code varchar(120) NULL,
            retry_after_utc datetime2(3) NULL,
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_seed_state_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_market_seed_state_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_market_seed_state_target CHECK(target_m15_candles BETWEEN 1 AND 200)
        );
    END;

    MERGE app.market_seed_state AS target
    USING (SELECT market_id FROM app.markets WHERE enabled=1) AS source
       ON target.market_id=source.market_id
    WHEN NOT MATCHED THEN
       INSERT(market_id,target_m15_candles,last_result)
       VALUES(source.market_id,64,'PENDING');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
