USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 UPDATE sm SET instrument_equivalence='EXACT_PAIR',qualification_allowed=1,
   evidence_source='Dukascopy JForex API Instrument.USDJPY plus official Historical Data Export; controlled USDJPY tick partitions downloaded and parsed by Aurex',
   review_status='VERIFIED',verified_at_utc=SYSUTCDATETIME()
 FROM app.instrument_source_mappings sm
 JOIN app.markets m ON m.market_id=sm.market_id
 WHERE m.symbol='USDJPY' AND sm.vendor='DUKASCOPY' AND sm.vendor_symbol='USDJPY';
 IF @@ROWCOUNT<>1 THROW 51000,'Expected exactly one USDJPY Dukascopy mapping',1;
 COMMIT TRANSACTION;
 PRINT 'Authoritative Dukascopy USDJPY mapping verified.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
