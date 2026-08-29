USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'app.research_lineages',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_lineages
        (
            research_lineage_id uniqueidentifier NOT NULL CONSTRAINT PK_research_lineages PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            market_id uniqueidentifier NOT NULL,
            hypothesis nvarchar(1000) NOT NULL,
            chosen_features_json nvarchar(max) NOT NULL,
            model_families_json nvarchar(max) NOT NULL,
            validation_policy_version varchar(80) NOT NULL,
            feature_version varchar(80) NOT NULL,
            label_version varchar(80) NOT NULL,
            label_horizon_bars int NOT NULL,
            label_horizon_minutes int NOT NULL,
            label_definition_hash char(64) NOT NULL,
            cost_model_version varchar(80) NOT NULL,
            source_identity varchar(100) NOT NULL,
            dirty_worktree bit NOT NULL,
            configuration_hash char(64) NOT NULL,
            development_start_utc datetime2(3) NOT NULL,
            development_end_utc datetime2(3) NOT NULL,
            holdout_start_utc datetime2(3) NOT NULL,
            holdout_end_utc datetime2(3) NOT NULL,
            status varchar(30) NOT NULL,
            created_by_user_id uniqueidentifier NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_lineages_created DEFAULT SYSUTCDATETIME(),
            closed_at_utc datetime2(3) NULL,
            CONSTRAINT FK_research_lineages_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_research_lineages_market FOREIGN KEY(market_id) REFERENCES app.markets(market_id),
            CONSTRAINT FK_research_lineages_user FOREIGN KEY(created_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT UQ_research_lineage_configuration UNIQUE(tenant_id,market_id,configuration_hash),
            CONSTRAINT CK_research_lineages_json CHECK(ISJSON(chosen_features_json)=1 AND ISJSON(model_families_json)=1),
            CONSTRAINT CK_research_lineages_horizon CHECK(label_horizon_bars>0 AND label_horizon_minutes>0),
            CONSTRAINT CK_research_lineages_period CHECK(development_start_utc<=development_end_utc AND development_end_utc<holdout_start_utc AND holdout_start_utc<=holdout_end_utc),
            CONSTRAINT CK_research_lineages_status CHECK(status IN ('RESERVED','CANDIDATE_FROZEN','HOLDOUT_CONSUMED','OWNER_REVIEW_REQUIRED','OWNER_APPROVED','REJECTED','CLOSED'))
        );
        CREATE INDEX IX_research_lineages_market_status ON app.research_lineages(tenant_id,market_id,status,created_at_utc DESC);
    END;

    IF COL_LENGTH(N'app.research_experiments',N'research_lineage_id') IS NULL
        ALTER TABLE app.research_experiments ADD research_lineage_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.research_experiments',N'validation_policy_version') IS NULL
        ALTER TABLE app.research_experiments ADD validation_policy_version varchar(80) NULL;
    IF COL_LENGTH(N'app.research_experiments',N'label_horizon_bars') IS NULL
        ALTER TABLE app.research_experiments ADD label_horizon_bars int NULL;
    IF COL_LENGTH(N'app.research_experiments',N'label_horizon_minutes') IS NULL
        ALTER TABLE app.research_experiments ADD label_horizon_minutes int NULL;
    IF COL_LENGTH(N'app.research_experiments',N'label_definition_hash') IS NULL
        ALTER TABLE app.research_experiments ADD label_definition_hash char(64) NULL;
    IF COL_LENGTH(N'app.research_experiments',N'dirty_worktree') IS NULL
        ALTER TABLE app.research_experiments ADD dirty_worktree bit NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_research_experiments_lineage')
        ALTER TABLE app.research_experiments ADD CONSTRAINT FK_research_experiments_lineage
            FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id);

    IF COL_LENGTH(N'app.holdout_candidates',N'research_lineage_id') IS NULL
        ALTER TABLE app.holdout_candidates ADD research_lineage_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'validation_policy_version') IS NULL
        ALTER TABLE app.holdout_candidates ADD validation_policy_version varchar(80) NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'label_horizon_bars') IS NULL
        ALTER TABLE app.holdout_candidates ADD label_horizon_bars int NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'label_definition_hash') IS NULL
        ALTER TABLE app.holdout_candidates ADD label_definition_hash char(64) NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'owner_reviewed_by_user_id') IS NULL
        ALTER TABLE app.holdout_candidates ADD owner_reviewed_by_user_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'owner_reviewed_at_utc') IS NULL
        ALTER TABLE app.holdout_candidates ADD owner_reviewed_at_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'owner_acknowledgement') IS NULL
        ALTER TABLE app.holdout_candidates ADD owner_acknowledgement varchar(80) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_holdout_candidates_lineage')
        ALTER TABLE app.holdout_candidates ADD CONSTRAINT FK_holdout_candidates_lineage
            FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id);
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_holdout_candidates_owner')
        ALTER TABLE app.holdout_candidates ADD CONSTRAINT FK_holdout_candidates_owner
            FOREIGN KEY(owner_reviewed_by_user_id) REFERENCES app.users(user_id);
    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_holdout_candidate_status')
        ALTER TABLE app.holdout_candidates DROP CONSTRAINT CK_holdout_candidate_status;
    ALTER TABLE app.holdout_candidates WITH CHECK ADD CONSTRAINT CK_holdout_candidate_status CHECK(status IN
        ('FROZEN','VALIDATION_REJECTED','EVALUATING','HOLDOUT_PASSED','HOLDOUT_REJECTED',
         'EVALUATION_FAILED','OWNER_REVIEW_REQUIRED','OWNER_APPROVED'));

    IF COL_LENGTH(N'app.model_versions',N'holdout_candidate_id') IS NULL
        ALTER TABLE app.model_versions ADD holdout_candidate_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.model_versions',N'research_lineage_id') IS NULL
        ALTER TABLE app.model_versions ADD research_lineage_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.model_versions',N'validation_policy_version') IS NULL
        ALTER TABLE app.model_versions ADD validation_policy_version varchar(80) NULL;
    IF COL_LENGTH(N'app.model_versions',N'feature_version') IS NULL
        ALTER TABLE app.model_versions ADD feature_version varchar(80) NULL;
    IF COL_LENGTH(N'app.model_versions',N'label_version') IS NULL
        ALTER TABLE app.model_versions ADD label_version varchar(80) NULL;
    IF COL_LENGTH(N'app.model_versions',N'cost_model_version') IS NULL
        ALTER TABLE app.model_versions ADD cost_model_version varchar(80) NULL;
    IF COL_LENGTH(N'app.model_versions',N'source_identity') IS NULL
        ALTER TABLE app.model_versions ADD source_identity varchar(100) NULL;
    IF COL_LENGTH(N'app.model_versions',N'dirty_worktree') IS NULL
        ALTER TABLE app.model_versions ADD dirty_worktree bit NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_model_versions_holdout')
        ALTER TABLE app.model_versions ADD CONSTRAINT FK_model_versions_holdout
            FOREIGN KEY(holdout_candidate_id) REFERENCES app.holdout_candidates(holdout_candidate_id);
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_model_versions_lineage')
        ALTER TABLE app.model_versions ADD CONSTRAINT FK_model_versions_lineage
            FOREIGN KEY(research_lineage_id) REFERENCES app.research_lineages(research_lineage_id);
    IF EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_models_status')
        ALTER TABLE app.model_versions DROP CONSTRAINT CK_models_status;
    ALTER TABLE app.model_versions WITH CHECK ADD CONSTRAINT CK_models_status CHECK(status IN
        ('REGISTERED','CANDIDATE','DEVELOPMENT_PASSED','VALIDATING','HOLDOUT_PASSED',
         'OWNER_APPROVED','VALIDATED','REJECTED','SUSPENDED','RETIRED'));

    IF COL_LENGTH(N'app.broker_market_rules',N'margin_factor_pct') IS NULL
        ALTER TABLE app.broker_market_rules ADD margin_factor_pct decimal(12,6) NULL;
    IF COL_LENGTH(N'app.risk_decisions',N'evidence_json') IS NULL
        ALTER TABLE app.risk_decisions ADD evidence_json nvarchar(max) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE name=N'CK_risk_decisions_evidence_json')
        EXEC(N'ALTER TABLE app.risk_decisions ADD CONSTRAINT CK_risk_decisions_evidence_json
            CHECK(evidence_json IS NULL OR ISJSON(evidence_json)=1)');

    IF OBJECT_ID(N'app.research_jobs',N'U') IS NULL
    BEGIN
        CREATE TABLE app.research_jobs
        (
            research_job_id uniqueidentifier NOT NULL CONSTRAINT PK_research_jobs PRIMARY KEY,
            tenant_id uniqueidentifier NOT NULL,
            job_type varchar(40) NOT NULL,
            request_json nvarchar(max) NOT NULL,
            status varchar(20) NOT NULL,
            idempotency_key char(64) NOT NULL,
            requested_by_user_id uniqueidentifier NULL,
            attempt_count int NOT NULL CONSTRAINT DF_research_jobs_attempts DEFAULT 0,
            lease_owner varchar(120) NULL,
            lease_expires_at_utc datetime2(3) NULL,
            progress_message nvarchar(500) NULL,
            result_json nvarchar(max) NULL,
            error_message nvarchar(1000) NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_research_jobs_created DEFAULT SYSUTCDATETIME(),
            started_at_utc datetime2(3) NULL,
            completed_at_utc datetime2(3) NULL,
            row_version rowversion NOT NULL,
            CONSTRAINT FK_research_jobs_tenant FOREIGN KEY(tenant_id) REFERENCES app.tenants(tenant_id),
            CONSTRAINT FK_research_jobs_user FOREIGN KEY(requested_by_user_id) REFERENCES app.users(user_id),
            CONSTRAINT UQ_research_jobs_idempotency UNIQUE(tenant_id,idempotency_key),
            CONSTRAINT CK_research_jobs_request CHECK(ISJSON(request_json)=1),
            CONSTRAINT CK_research_jobs_result CHECK(result_json IS NULL OR ISJSON(result_json)=1),
            CONSTRAINT CK_research_jobs_status CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED'))
        );
        CREATE INDEX IX_research_jobs_claim ON app.research_jobs(status,created_at_utc) INCLUDE(job_type,lease_expires_at_utc);
    END;

    COMMIT TRANSACTION;
    PRINT 'Aurex canonical model governance and durable jobs migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
