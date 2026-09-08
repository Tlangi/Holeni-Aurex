USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 ;WITH ranked AS (
  SELECT j.backfill_job_id,
   DENSE_RANK() OVER(ORDER BY CASE WHEN m.symbol='USDJPY' THEN 0 ELSE 1 END,m.symbol)-1 market_rank,
   DATEDIFF(day,CONVERT(datetime2,'2000-01-01'),j.partition_start_utc) partition_rank
  FROM app.historical_backfill_jobs j JOIN app.markets m ON m.market_id=j.market_id
 )
 UPDATE j SET priority=r.market_rank*100000000+r.partition_rank,updated_at_utc=SYSUTCDATETIME()
 FROM app.historical_backfill_jobs j JOIN ranked r ON r.backfill_job_id=j.backfill_job_id;
 COMMIT TRANSACTION;
 PRINT 'Historical backfill now completes USDJPY before proceeding sequentially through other markets.';
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
GO
