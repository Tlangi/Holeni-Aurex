USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
 BEGIN TRANSACTION;

 -- Legacy columns remain for rollback/schema compatibility, but have no
 -- trading, sizing or confidence-threshold authority from this migration onward.
 UPDATE app.risk_versions
    SET preferred_daily_return_pct=0.0000,
        daily_profit_lock_pct=0.0000,
        profit_giveback_limit_pct=0.0000;

 -- Clear only obsolete profit-derived blocks. The next account sync
 -- independently reapplies every loss and drawdown risk gate.
 UPDATE app.daily_risk_ledger
    SET status='CURRENT',status_reason=NULL,profit_protection_state='NORMAL',
        updated_at_utc=SYSUTCDATETIME()
  WHERE status_reason IN ('DAILY_PROFIT_LOCK','PROFIT_GIVEBACK_LIMIT');

 COMMIT TRANSACTION;
 PRINT 'Daily profit quota authority removed; loss and drawdown controls retained.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
