USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.account_snapshots',N'source_equity') IS NULL
        ALTER TABLE app.account_snapshots ADD source_equity decimal(19,6) NULL;
    IF COL_LENGTH(N'app.account_snapshots',N'source_balance') IS NULL
        ALTER TABLE app.account_snapshots ADD source_balance decimal(19,6) NULL;
    IF COL_LENGTH(N'app.account_snapshots',N'source_available_funds') IS NULL
        ALTER TABLE app.account_snapshots ADD source_available_funds decimal(19,6) NULL;
    IF COL_LENGTH(N'app.account_snapshots',N'source_margin_used') IS NULL
        ALTER TABLE app.account_snapshots ADD source_margin_used decimal(19,6) NULL;
    IF COL_LENGTH(N'app.account_snapshots',N'source_profit_loss') IS NULL
        ALTER TABLE app.account_snapshots ADD source_profit_loss decimal(19,6) NULL;

    EXEC sys.sp_executesql N'
      UPDATE app.account_snapshots
         SET source_equity=COALESCE(source_equity,equity/NULLIF(conversion_rate,0)),
             source_balance=COALESCE(source_balance,balance/NULLIF(conversion_rate,0)),
             source_available_funds=COALESCE(source_available_funds,available_funds/NULLIF(conversion_rate,0)),
             source_margin_used=COALESCE(source_margin_used,margin_used/NULLIF(conversion_rate,0)),
             source_profit_loss=COALESCE(source_profit_loss,profit_loss/NULLIF(conversion_rate,0));';

    IF COL_LENGTH(N'app.daily_risk_ledger',N'opening_equity_source') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD opening_equity_source decimal(19,6) NULL;
    IF COL_LENGTH(N'app.daily_risk_ledger',N'current_equity_source') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD current_equity_source decimal(19,6) NULL;
    IF COL_LENGTH(N'app.daily_risk_ledger',N'peak_equity_source') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD peak_equity_source decimal(19,6) NULL;
    IF COL_LENGTH(N'app.daily_risk_ledger',N'source_currency') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD source_currency char(3) NULL;
    IF COL_LENGTH(N'app.daily_risk_ledger',N'risk_return_basis') IS NULL
        ALTER TABLE app.daily_risk_ledger ADD risk_return_basis varchar(30) NOT NULL
            CONSTRAINT DF_daily_risk_return_basis DEFAULT 'SOURCE_CURRENCY';

    -- Only replace the original defaults. Preserve any separately configured
    -- owner policy. Zero means there is no daily profit objective.
    UPDATE app.risk_versions
       SET preferred_daily_return_pct=0.0000,
           profit_protection_pct=0.5000
     WHERE preferred_daily_return_pct=2.0000
       AND profit_protection_pct=2.0000;

    COMMIT TRANSACTION;
    PRINT 'Native-currency profit protection migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
