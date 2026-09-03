USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.markets',N'market_tier') IS NULL
        ALTER TABLE app.markets ADD market_tier tinyint NOT NULL
            CONSTRAINT DF_markets_tier DEFAULT 1;
    IF COL_LENGTH(N'app.markets',N'research_enabled') IS NULL
        ALTER TABLE app.markets ADD research_enabled bit NOT NULL
            CONSTRAINT DF_markets_research_enabled DEFAULT 1;
    IF COL_LENGTH(N'app.markets',N'training_enabled') IS NULL
        ALTER TABLE app.markets ADD training_enabled bit NOT NULL
            CONSTRAINT DF_markets_training_enabled DEFAULT 1;
    IF COL_LENGTH(N'app.markets',N'signal_enabled') IS NULL
        ALTER TABLE app.markets ADD signal_enabled bit NOT NULL
            CONSTRAINT DF_markets_signal_enabled DEFAULT 1;
    IF COL_LENGTH(N'app.markets',N'demo_trading_enabled') IS NULL
        ALTER TABLE app.markets ADD demo_trading_enabled bit NOT NULL
            CONSTRAINT DF_markets_demo_enabled DEFAULT 1;
    IF COL_LENGTH(N'app.markets',N'live_trading_enabled') IS NULL
        ALTER TABLE app.markets ADD live_trading_enabled bit NOT NULL
            CONSTRAINT DF_markets_live_enabled DEFAULT 0;
    IF COL_LENGTH(N'app.markets',N'reporting_currency') IS NULL
        ALTER TABLE app.markets ADD reporting_currency char(3) NOT NULL
            CONSTRAINT DF_markets_reporting_currency DEFAULT 'ZAR';
    IF COL_LENGTH(N'app.markets',N'pip_size') IS NULL
        ALTER TABLE app.markets ADD pip_size decimal(18,8) NULL;
    IF COL_LENGTH(N'app.markets',N'tick_size') IS NULL
        ALTER TABLE app.markets ADD tick_size decimal(18,8) NULL;
    IF COL_LENGTH(N'app.markets',N'max_spread_bps') IS NULL
        ALTER TABLE app.markets ADD max_spread_bps decimal(12,4) NULL;
    IF COL_LENGTH(N'app.markets',N'slippage_assumption_bps') IS NULL
        ALTER TABLE app.markets ADD slippage_assumption_bps decimal(12,4) NULL;
    IF COL_LENGTH(N'app.markets',N'default_timeframe') IS NULL
        ALTER TABLE app.markets ADD default_timeframe varchar(10) NOT NULL
            CONSTRAINT DF_markets_default_timeframe DEFAULT 'M5';
    IF COL_LENGTH(N'app.markets',N'confirmation_timeframe') IS NULL
        ALTER TABLE app.markets ADD confirmation_timeframe varchar(10) NOT NULL
            CONSTRAINT DF_markets_confirmation_timeframe DEFAULT 'M15';
    IF COL_LENGTH(N'app.markets',N'risk_profile') IS NULL
        ALTER TABLE app.markets ADD risk_profile varchar(40) NOT NULL
            CONSTRAINT DF_markets_risk_profile DEFAULT 'UNCLASSIFIED';
    IF COL_LENGTH(N'app.markets',N'broker_instrument_type') IS NULL
        ALTER TABLE app.markets ADD broker_instrument_type varchar(40) NULL;
    IF COL_LENGTH(N'app.markets',N'broker_resolved_at_utc') IS NULL
        ALTER TABLE app.markets ADD broker_resolved_at_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.markets',N'execution_promotion_required') IS NULL
        ALTER TABLE app.markets ADD execution_promotion_required bit NOT NULL
            CONSTRAINT DF_markets_promotion_required DEFAULT 0;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;

    UPDATE app.markets SET market_tier=1,research_enabled=1,training_enabled=1,
        signal_enabled=1,demo_trading_enabled=1,live_trading_enabled=0,
        reporting_currency='ZAR',execution_promotion_required=0,
        risk_profile=CASE symbol WHEN 'GERMANY40' THEN 'INDEX_CASH'
                     WHEN 'USDJPY' THEN 'FX_JPY' ELSE 'FX_MAJOR' END,
        pip_size=CASE WHEN symbol='USDJPY' THEN 0.01 WHEN symbol='GERMANY40' THEN 1 ELSE 0.0001 END,
        tick_size=CASE WHEN symbol='USDJPY' THEN 0.001 WHEN symbol='GERMANY40' THEN 0.1 ELSE 0.00001 END
    WHERE symbol IN ('EURUSD','GBPUSD','USDJPY','GERMANY40');

    MERGE app.markets AS target
    USING (VALUES
      ('GBPJPY','GBP/JPY','CS.D.GBPJPY.CFD.IP','FX',2,'GBP','JPY',3,CAST(0.01 AS decimal(18,8)),CAST(0.001 AS decimal(18,8)),'FX_CROSS_JPY','CURRENCIES'),
      ('EURJPY','EUR/JPY','CS.D.EURJPY.CFD.IP','FX',2,'EUR','JPY',3,CAST(0.01 AS decimal(18,8)),CAST(0.001 AS decimal(18,8)),'FX_CROSS_JPY','CURRENCIES'),
      ('XAUUSD','Spot Gold ($1)','CS.D.CFDGOLD.BMU.IP','METAL',2,'XAU','USD',2,CAST(0.01 AS decimal(18,8)),CAST(0.01 AS decimal(18,8)),'SPOT_GOLD','CURRENCIES'),
      ('AUDJPY','AUD/JPY','CS.D.AUDJPY.CFD.IP','FX',3,'AUD','JPY',3,CAST(0.01 AS decimal(18,8)),CAST(0.001 AS decimal(18,8)),'FX_CROSS_JPY','CURRENCIES'),
      ('USDZAR','USD/ZAR','CS.D.USDZAR.CFD.IP','FX',3,'USD','ZAR',5,CAST(0.0001 AS decimal(18,8)),CAST(0.00001 AS decimal(18,8)),'FX_EMERGING','CURRENCIES')
    ) AS source(symbol,display_name,ig_epic,asset_class,market_tier,base_currency,
                quote_currency,price_digits,pip_size,tick_size,risk_profile,broker_type)
      ON target.symbol=source.symbol
    WHEN MATCHED THEN UPDATE SET display_name=source.display_name,ig_epic=source.ig_epic,
      asset_class=source.asset_class,market_tier=source.market_tier,
      base_currency=source.base_currency,quote_currency=source.quote_currency,
      price_digits=source.price_digits,pip_size=source.pip_size,tick_size=source.tick_size,
      risk_profile=source.risk_profile,broker_instrument_type=source.broker_type,
      broker_resolved_at_utc=SYSUTCDATETIME(),enabled=1,research_enabled=1,training_enabled=1,
      signal_enabled=0,demo_trading_enabled=0,live_trading_enabled=0,
      reporting_currency='ZAR',default_timeframe='M5',confirmation_timeframe='M15',
      calendar_code='FX_24X5',market_timezone='UTC',session_open_local=NULL,
      session_close_local=NULL,execution_promotion_required=1
    WHEN NOT MATCHED THEN INSERT
      (market_id,symbol,display_name,ig_epic,base_currency,quote_currency,price_digits,enabled,
       asset_class,calendar_code,market_timezone,session_open_local,session_close_local,
       market_tier,research_enabled,training_enabled,signal_enabled,demo_trading_enabled,
       live_trading_enabled,reporting_currency,pip_size,tick_size,default_timeframe,
       confirmation_timeframe,risk_profile,broker_instrument_type,broker_resolved_at_utc,
       execution_promotion_required)
    VALUES(NEWID(),source.symbol,source.display_name,source.ig_epic,source.base_currency,
       source.quote_currency,source.price_digits,1,source.asset_class,'FX_24X5','UTC',NULL,NULL,
       source.market_tier,1,1,0,0,0,'ZAR',source.pip_size,source.tick_size,'M5','M15',
       source.risk_profile,source.broker_type,SYSUTCDATETIME(),1);

    IF OBJECT_ID(N'app.market_seed_state',N'U') IS NOT NULL
    BEGIN
        MERGE app.market_seed_state AS target
        USING (SELECT market_id FROM app.markets WHERE symbol IN
          ('GBPJPY','EURJPY','XAUUSD','AUDJPY','USDZAR')) AS source
          ON target.market_id=source.market_id
        WHEN NOT MATCHED THEN INSERT(market_id,target_m15_candles,last_result)
          VALUES(source.market_id,64,'PENDING');
    END;

    IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_markets_tier')
        ALTER TABLE app.markets ADD CONSTRAINT CK_markets_tier CHECK(market_tier IN (1,2,3));
    IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_markets_tier3_execution')
        ALTER TABLE app.markets ADD CONSTRAINT CK_markets_tier3_execution CHECK(
          market_tier<>3 OR (signal_enabled=0 AND demo_trading_enabled=0 AND live_trading_enabled=0));
    IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_markets_live_requires_demo')
        ALTER TABLE app.markets ADD CONSTRAINT CK_markets_live_requires_demo CHECK(
          live_trading_enabled=0 OR demo_trading_enabled=1);

    COMMIT TRANSACTION;
    PRINT 'Tiered market registry migration completed successfully.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
