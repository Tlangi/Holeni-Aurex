USE [ForexSaas];
GO

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER VIEW app.v_market_candles
AS
    SELECT
        c.candle_id,
        c.market_id,
        m.symbol,
        m.display_name,
        c.timeframe,
        c.open_time_utc,
        CAST((c.open_time_utc AT TIME ZONE 'UTC')
             AT TIME ZONE 'South Africa Standard Time' AS datetime2(3)) AS open_time_sast,
        c.close_time_utc,
        CAST((c.close_time_utc AT TIME ZONE 'UTC')
             AT TIME ZONE 'South Africa Standard Time' AS datetime2(3)) AS close_time_sast,
        c.[open],
        c.high,
        c.low,
        c.[close],
        c.tick_count,
        c.source,
        c.completed,
        c.created_at_utc
    FROM app.candles AS c
    JOIN app.markets AS m
      ON m.market_id=c.market_id;
GO

GRANT SELECT ON OBJECT::app.v_market_candles TO [ForexSaasApp];
GO
