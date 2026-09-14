USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID(N'app.three_view_research_quality_snapshots', N'U') IS NULL
    BEGIN
        CREATE TABLE app.three_view_research_quality_snapshots (
            quality_snapshot_id uniqueidentifier NOT NULL
                CONSTRAINT PK_three_view_research_quality_snapshots PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            view_code varchar(32) NOT NULL,
            captured_at_utc datetime2(3) NOT NULL
                CONSTRAINT DF_three_view_quality_captured DEFAULT SYSUTCDATETIME(),
            first_utc datetime2(3) NULL,
            last_utc datetime2(3) NULL,
            observed_count int NOT NULL,
            expected_count int NOT NULL,
            missing_count int NOT NULL,
            quality_pct decimal(9,4) NULL,
            complete_m1_gap_intervals int NOT NULL,
            partial_m1_gap_intervals int NOT NULL,
            absent_m1_gap_intervals int NOT NULL,
            score_authority varchar(64) NOT NULL,
            qualification_status varchar(16) NOT NULL,
            policy_sha256 char(64) NOT NULL,
            evidence_sha256 char(64) NOT NULL,
            evidence_json nvarchar(max) NOT NULL,
            CONSTRAINT FK_three_view_quality_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_three_view_quality_view CHECK(view_code IN
                ('RAW_IG','HYBRID_RESEARCH','CURRENT_IG_EXECUTION')),
            CONSTRAINT CK_three_view_quality_nonnegative CHECK(
                observed_count>=0 AND expected_count>=0 AND missing_count>=0 AND
                complete_m1_gap_intervals>=0 AND partial_m1_gap_intervals>=0 AND
                absent_m1_gap_intervals>=0),
            CONSTRAINT CK_three_view_quality_status CHECK(qualification_status IN ('PASS','BLOCKED')),
            CONSTRAINT CK_three_view_quality_json CHECK(ISJSON(evidence_json)=1)
        );
        CREATE INDEX IX_three_view_quality_latest ON
            app.three_view_research_quality_snapshots(market_id,view_code,captured_at_utc DESC);
    END;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
IF OBJECT_ID(N'app.trg_three_view_quality_append_only',N'TR') IS NULL
 EXEC(N'CREATE TRIGGER app.trg_three_view_quality_append_only ON app.three_view_research_quality_snapshots AFTER UPDATE, DELETE AS BEGIN THROW 51057, ''Three-view quality evidence is append-only'', 1; END');
GO
