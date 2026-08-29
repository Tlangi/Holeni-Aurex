USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    MERGE app.market_holidays AS target
    USING (VALUES
        ('XETRA_REGULAR',CONVERT(date,'2026-01-01'),N'New Year''s Day'),
        ('XETRA_REGULAR',CONVERT(date,'2026-04-03'),N'Good Friday'),
        ('XETRA_REGULAR',CONVERT(date,'2026-04-06'),N'Easter Monday'),
        ('XETRA_REGULAR',CONVERT(date,'2026-05-01'),N'Labour Day'),
        ('XETRA_REGULAR',CONVERT(date,'2026-12-24'),N'Christmas Eve'),
        ('XETRA_REGULAR',CONVERT(date,'2026-12-25'),N'Christmas Day'),
        ('XETRA_REGULAR',CONVERT(date,'2026-12-31'),N'New Year''s Eve')
    ) AS source(calendar_code,holiday_date,holiday_name)
       ON target.calendar_code=source.calendar_code AND target.holiday_date=source.holiday_date
    WHEN MATCHED THEN UPDATE SET holiday_name=source.holiday_name,session_close_local=NULL
    WHEN NOT MATCHED THEN INSERT(calendar_code,holiday_date,holiday_name,session_close_local)
        VALUES(source.calendar_code,source.holiday_date,source.holiday_name,NULL);

    COMMIT TRANSACTION;
    PRINT 'Seeded the official 2026 Xetra non-trading calendar.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
