USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    MERGE app.markets AS target
    USING (VALUES
        ('GERMANY40',N'Germany 40 Cash (E1)','IX.D.DAX.BMU.IP','EUR','EUR',1)
    ) AS source(symbol,display_name,ig_epic,base_currency,quote_currency,price_digits)
       ON target.symbol=source.symbol
    WHEN MATCHED THEN UPDATE SET
        display_name=source.display_name,
        ig_epic=source.ig_epic,
        base_currency=source.base_currency,
        quote_currency=source.quote_currency,
        price_digits=source.price_digits,
        enabled=1
    WHEN NOT MATCHED THEN INSERT
        (market_id,symbol,display_name,ig_epic,base_currency,quote_currency,price_digits,enabled)
        VALUES(NEWID(),source.symbol,source.display_name,source.ig_epic,
               source.base_currency,source.quote_currency,source.price_digits,1);

    INSERT app.market_execution_states(tenant_id,market_id,mode,new_orders_enabled,reason)
    SELECT t.tenant_id,m.market_id,'SHADOW',0,N'Germany 40 awaiting market-specific validation'
    FROM app.tenants t
    CROSS JOIN app.markets m
    WHERE m.symbol='GERMANY40'
      AND NOT EXISTS
          (SELECT 1 FROM app.market_execution_states s
           WHERE s.tenant_id=t.tenant_id AND s.market_id=m.market_id);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
