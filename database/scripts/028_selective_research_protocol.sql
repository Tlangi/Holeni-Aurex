USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.research_target_specs',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_target_specs
        (
            research_target_spec_id uniqueidentifier NOT NULL CONSTRAINT PK_research_target_specs PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            protocol_version varchar(80) NOT NULL,
            target_version varchar(80) NOT NULL,
            target_sha256 char(64) NOT NULL,
            horizon_bars int NOT NULL,
            target_mode varchar(40) NOT NULL,
            configuration_json nvarchar(max) NOT NULL,
            active bit NOT NULL CONSTRAINT DF_research_target_specs_active DEFAULT 1,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_target_specs_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_research_target_specs_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_research_target_specs_hash UNIQUE(market_id,target_sha256),
            CONSTRAINT CK_research_target_specs_json CHECK(ISJSON(configuration_json)=1),
            CONSTRAINT CK_research_target_specs_horizon CHECK(horizon_bars>0)
        );
        CREATE INDEX IX_research_target_specs_market ON app.research_target_specs(market_id,active,created_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.dataset_boundary_audits',N'U') IS NULL
    BEGIN
        CREATE TABLE app.dataset_boundary_audits
        (
            dataset_boundary_audit_id uniqueidentifier NOT NULL CONSTRAINT PK_dataset_boundary_audits PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            research_lineage_id uniqueidentifier NULL,
            research_target_spec_id uniqueidentifier NOT NULL,
            audit_version varchar(80) NOT NULL,
            source_start_utc datetime2(3) NOT NULL,
            source_end_utc datetime2(3) NOT NULL,
            source_rows int NOT NULL,
            feature_rows int NOT NULL,
            dataset_sha256 char(64) NOT NULL,
            passed bit NOT NULL,
            gates_json nvarchar(max) NOT NULL,
            details_json nvarchar(max) NOT NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_dataset_boundary_audits_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_dataset_boundary_audits_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_dataset_boundary_audits_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_dataset_boundary_audits_lineage FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id),
            CONSTRAINT FK_dataset_boundary_audits_target FOREIGN KEY(research_target_spec_id) REFERENCES app.research_target_specs(research_target_spec_id),
            CONSTRAINT CK_dataset_boundary_audits_rows CHECK(source_rows>0 AND feature_rows>=0),
            CONSTRAINT CK_dataset_boundary_audits_json CHECK(ISJSON(gates_json)=1 AND ISJSON(details_json)=1)
        );
        CREATE INDEX IX_dataset_boundary_audits_market ON app.dataset_boundary_audits(tenant_id,market_id,evaluated_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.candidate_lifecycle_events',N'U') IS NULL
    BEGIN
        CREATE TABLE app.candidate_lifecycle_events
        (
            candidate_lifecycle_event_id uniqueidentifier NOT NULL CONSTRAINT PK_candidate_lifecycle_events PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            research_lineage_id uniqueidentifier NULL,
            holdout_candidate_id uniqueidentifier NULL,
            model_version_id uniqueidentifier NULL,
            from_state varchar(30) NOT NULL,
            to_state varchar(30) NOT NULL,
            transition_reason nvarchar(500) NOT NULL,
            evidence_sha256 char(64) NOT NULL,
            evidence_json nvarchar(max) NOT NULL,
            changed_by_user_id uniqueidentifier NULL,
            changed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_candidate_lifecycle_events_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_candidate_lifecycle_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_candidate_lifecycle_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_candidate_lifecycle_lineage FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id),
            CONSTRAINT FK_candidate_lifecycle_holdout FOREIGN KEY(holdout_candidate_id) REFERENCES app.holdout_candidates(holdout_candidate_id),
            CONSTRAINT FK_candidate_lifecycle_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT FK_candidate_lifecycle_user FOREIGN KEY(changed_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT CK_candidate_lifecycle_json CHECK(ISJSON(evidence_json)=1),
            CONSTRAINT CK_candidate_lifecycle_entity CHECK(research_lineage_id IS NOT NULL OR holdout_candidate_id IS NOT NULL OR model_version_id IS NOT NULL)
        );
        CREATE INDEX IX_candidate_lifecycle_market ON app.candidate_lifecycle_events(tenant_id,market_id,changed_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.market_data_quarantine',N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_data_quarantine
        (
            market_data_quarantine_id uniqueidentifier NOT NULL CONSTRAINT PK_market_data_quarantine PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            provider varchar(40) NOT NULL,
            source_reference nvarchar(260) NOT NULL,
            source_sha256 char(64) NULL,
            source_row_number int NULL,
            rejection_code varchar(60) NOT NULL,
            rejection_detail nvarchar(500) NOT NULL,
            raw_payload_json nvarchar(max) NULL,
            status varchar(20) NOT NULL CONSTRAINT DF_market_data_quarantine_status DEFAULT 'QUARANTINED',
            observed_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_data_quarantine_time DEFAULT SYSUTCDATETIME(),
            reviewed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_market_data_quarantine_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT CK_market_data_quarantine_row CHECK(source_row_number IS NULL OR source_row_number>0),
            CONSTRAINT CK_market_data_quarantine_json CHECK(raw_payload_json IS NULL OR ISJSON(raw_payload_json)=1),
            CONSTRAINT CK_market_data_quarantine_status CHECK(status IN ('QUARANTINED','REVIEWED','DISMISSED','REIMPORT_APPROVED'))
        );
        CREATE INDEX IX_market_data_quarantine_market ON app.market_data_quarantine(market_id,status,observed_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.market_data_recovery_jobs',N'U') IS NULL
    BEGIN
        CREATE TABLE app.market_data_recovery_jobs
        (
            market_data_recovery_job_id uniqueidentifier NOT NULL CONSTRAINT PK_market_data_recovery_jobs PRIMARY KEY,
            market_id uniqueidentifier NOT NULL,
            timeframe varchar(10) NOT NULL,
            gap_start_utc datetime2(3) NOT NULL,
            gap_end_utc datetime2(3) NOT NULL,
            maximum_requested_rows int NOT NULL,
            status varchar(20) NOT NULL,
            attempt_count int NOT NULL CONSTRAINT DF_market_data_recovery_attempts DEFAULT 0,
            retry_after_utc datetime2(3) NULL,
            last_error_code varchar(120) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_market_data_recovery_created DEFAULT SYSUTCDATETIME(),
            completed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_market_data_recovery_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT UQ_market_data_recovery_gap UNIQUE(market_id,timeframe,gap_start_utc,gap_end_utc),
            CONSTRAINT CK_market_data_recovery_period CHECK(gap_start_utc<=gap_end_utc),
            CONSTRAINT CK_market_data_recovery_rows CHECK(maximum_requested_rows BETWEEN 1 AND 500),
            CONSTRAINT CK_market_data_recovery_status CHECK(status IN ('QUEUED','SESSION_DEFERRED','RUNNING','COMPLETED','QUOTA_DEFERRED','FAILED'))
        );
    END;

    IF OBJECT_ID(N'app.model_monitoring_snapshots',N'U') IS NULL
    BEGIN
        CREATE TABLE app.model_monitoring_snapshots
        (
            model_monitoring_snapshot_id uniqueidentifier NOT NULL CONSTRAINT PK_model_monitoring_snapshots PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            model_version_id uniqueidentifier NULL,
            feature_drift_score decimal(18,8) NULL,
            calibration_drift_score decimal(18,8) NULL,
            cost_drift_score decimal(18,8) NULL,
            regime_coverage decimal(18,8) NULL,
            status varchar(20) NOT NULL,
            details_json nvarchar(max) NOT NULL,
            evaluated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_model_monitoring_time DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_model_monitoring_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_model_monitoring_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_model_monitoring_model FOREIGN KEY(model_version_id) REFERENCES app.model_versions(model_version_id),
            CONSTRAINT CK_model_monitoring_status CHECK(status IN ('BASELINE','CURRENT','WARN','FAIL','MODEL_UNAVAILABLE')),
            CONSTRAINT CK_model_monitoring_json CHECK(ISJSON(details_json)=1)
        );
        CREATE INDEX IX_model_monitoring_market ON app.model_monitoring_snapshots(tenant_id,market_id,evaluated_at_utc DESC);
    END;

    COMMIT TRANSACTION;
    PRINT 'Aurex selective research protocol migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
