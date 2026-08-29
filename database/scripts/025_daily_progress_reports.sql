USE [ForexSaas];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.daily_progress_reports',N'U') IS NULL
    BEGIN
        CREATE TABLE app.daily_progress_reports
        (
            daily_progress_report_id uniqueidentifier NOT NULL CONSTRAINT PK_daily_progress_reports PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            report_date_sast date NOT NULL,
            recipient_email nvarchar(320) NOT NULL,
            subject nvarchar(300) NOT NULL,
            body_sha256 char(64) NOT NULL,
            status varchar(20) NOT NULL,
            summary_json nvarchar(max) NOT NULL,
            claimed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_daily_reports_claimed DEFAULT SYSUTCDATETIME(),
            sent_at_utc datetime2(3) NULL,
            failed_at_utc datetime2(3) NULL,
            failure_code varchar(100) NULL,
            CONSTRAINT FK_daily_reports_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT UQ_daily_reports_tenant_date UNIQUE(tenant_id,report_date_sast),
            CONSTRAINT CK_daily_reports_status CHECK(status IN ('SENDING','SENT','FAILED','SKIPPED')),
            CONSTRAINT CK_daily_reports_summary CHECK(ISJSON(summary_json)=1)
        );
        CREATE INDEX IX_daily_reports_status_date
            ON app.daily_progress_reports(status,report_date_sast DESC);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

