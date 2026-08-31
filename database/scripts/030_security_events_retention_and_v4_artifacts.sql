USE [ForexSaas];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH(N'app.holdout_candidates',N'research_target_spec_id') IS NULL
        ALTER TABLE app.holdout_candidates ADD research_target_spec_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'research_protocol_version') IS NULL
        ALTER TABLE app.holdout_candidates ADD research_protocol_version varchar(80) NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'tournament_experiment_id') IS NULL
        ALTER TABLE app.holdout_candidates ADD tournament_experiment_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.holdout_candidates',N'challenger_key') IS NULL
        ALTER TABLE app.holdout_candidates ADD challenger_key varchar(80) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_holdout_candidates_target_spec')
        ALTER TABLE app.holdout_candidates ADD CONSTRAINT FK_holdout_candidates_target_spec
            FOREIGN KEY(research_target_spec_id) REFERENCES app.research_target_specs(research_target_spec_id);
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_holdout_candidates_tournament')
        ALTER TABLE app.holdout_candidates ADD CONSTRAINT FK_holdout_candidates_tournament
            FOREIGN KEY(tournament_experiment_id) REFERENCES app.research_experiments(experiment_id);

    IF COL_LENGTH(N'app.model_versions',N'research_target_spec_id') IS NULL
        ALTER TABLE app.model_versions ADD research_target_spec_id uniqueidentifier NULL;
    IF COL_LENGTH(N'app.model_versions',N'research_protocol_version') IS NULL
        ALTER TABLE app.model_versions ADD research_protocol_version varchar(80) NULL;
    IF COL_LENGTH(N'app.model_versions',N'challenger_key') IS NULL
        ALTER TABLE app.model_versions ADD challenger_key varchar(80) NULL;
    IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_model_versions_target_spec')
        ALTER TABLE app.model_versions ADD CONSTRAINT FK_model_versions_target_spec
            FOREIGN KEY(research_target_spec_id) REFERENCES app.research_target_specs(research_target_spec_id);

    IF COL_LENGTH(N'app.users',N'locked_until_utc') IS NULL
        ALTER TABLE app.users ADD locked_until_utc datetime2(3) NULL;
    IF COL_LENGTH(N'app.users',N'failed_login_count') IS NULL
        ALTER TABLE app.users ADD failed_login_count int NOT NULL CONSTRAINT DF_users_failed_login_count DEFAULT 0;
    IF COL_LENGTH(N'app.users',N'mfa_required') IS NULL
        ALTER TABLE app.users ADD mfa_required bit NOT NULL CONSTRAINT DF_users_mfa_required DEFAULT 0;

    IF OBJECT_ID(N'app.authentication_attempts',N'U') IS NULL
    BEGIN
        CREATE TABLE app.authentication_attempts
        (
            authentication_attempt_id uniqueidentifier NOT NULL CONSTRAINT PK_authentication_attempts PRIMARY KEY,
            email_hash varbinary(32) NOT NULL,
            remote_address_hash varbinary(32) NOT NULL,
            succeeded bit NOT NULL,
            failure_code varchar(40) NULL,
            attempted_at_utc datetime2(3) NOT NULL CONSTRAINT DF_authentication_attempts_time DEFAULT SYSUTCDATETIME()
        );
        CREATE INDEX IX_auth_attempt_email_time ON app.authentication_attempts(email_hash,attempted_at_utc DESC);
        CREATE INDEX IX_auth_attempt_remote_time ON app.authentication_attempts(remote_address_hash,attempted_at_utc DESC);
    END;

    IF OBJECT_ID(N'app.economic_event_snapshots',N'U') IS NULL
    BEGIN
        CREATE TABLE app.economic_event_snapshots
        (
            economic_event_snapshot_id uniqueidentifier NOT NULL CONSTRAINT PK_economic_event_snapshots PRIMARY KEY,
            macro_evidence_id uniqueidentifier NULL,
            source_code varchar(60) NOT NULL,
            external_key nvarchar(300) NOT NULL,
            currency char(3) NOT NULL,
            event_at_utc datetime2(3) NOT NULL,
            impact varchar(20) NOT NULL,
            classification varchar(40) NOT NULL,
            title nvarchar(500) NOT NULL,
            retrieved_at_utc datetime2(3) NOT NULL,
            available_from_utc datetime2(3) NOT NULL,
            payload_sha256 char(64) NOT NULL,
            payload_json nvarchar(max) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_event_snapshots_created DEFAULT SYSUTCDATETIME(),
            CONSTRAINT FK_event_snapshots_evidence FOREIGN KEY(macro_evidence_id) REFERENCES app.macro_evidence(macro_evidence_id),
            CONSTRAINT UQ_event_snapshots_vintage UNIQUE(source_code,external_key,retrieved_at_utc,payload_sha256),
            CONSTRAINT CK_event_snapshots_json CHECK(ISJSON(payload_json)=1),
            CONSTRAINT CK_event_snapshots_availability CHECK(available_from_utc>=retrieved_at_utc)
        );
        CREATE INDEX IX_event_snapshots_time ON app.economic_event_snapshots(currency,event_at_utc,available_from_utc);
    END;

    IF OBJECT_ID(N'app.data_retention_policies',N'U') IS NULL
    BEGIN
        CREATE TABLE app.data_retention_policies
        (
            retention_policy_id uniqueidentifier NOT NULL CONSTRAINT PK_data_retention_policies PRIMARY KEY,
            entity_code varchar(60) NOT NULL CONSTRAINT UQ_data_retention_entity UNIQUE,
            hot_retention_days int NOT NULL,
            archive_retention_days int NOT NULL,
            archive_required bit NOT NULL,
            enabled bit NOT NULL CONSTRAINT DF_retention_enabled DEFAULT 1,
            policy_json nvarchar(max) NOT NULL,
            created_at_utc datetime2(3) NOT NULL CONSTRAINT DF_retention_created DEFAULT SYSUTCDATETIME(),
            updated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_retention_updated DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_retention_days CHECK(hot_retention_days>0 AND archive_retention_days>=hot_retention_days),
            CONSTRAINT CK_retention_json CHECK(ISJSON(policy_json)=1)
        );
    END;

    MERGE app.data_retention_policies AS target
    USING (VALUES
      ('CANDLES',730,2555,1,N'{"partition":"market/timeframe/month","delete_requires_verified_archive":true}'),
      ('AUDIT_LOGS',2555,2555,1,N'{"immutable":true,"delete_requires_owner_approval":true}'),
      ('RESEARCH_EXPERIMENTS',730,2555,1,N'{"retain_summary":true,"compress_payloads":true}'),
      ('AUTH_ATTEMPTS',90,365,0,N'{"contains_only_hashes":true}'),
      ('QUARANTINE',180,730,1,N'{"retain_review_decision":true}'))
      AS source(entity_code,hot_days,archive_days,archive_required,policy_json)
    ON target.entity_code=source.entity_code
    WHEN MATCHED THEN UPDATE SET hot_retention_days=source.hot_days,
        archive_retention_days=source.archive_days,archive_required=source.archive_required,
        policy_json=source.policy_json,updated_at_utc=SYSUTCDATETIME()
    WHEN NOT MATCHED THEN INSERT(retention_policy_id,entity_code,hot_retention_days,
        archive_retention_days,archive_required,policy_json)
        VALUES(NEWID(),source.entity_code,source.hot_days,source.archive_days,
               source.archive_required,source.policy_json);

    IF OBJECT_ID(N'app.backup_replications',N'U') IS NULL
    BEGIN
        CREATE TABLE app.backup_replications
        (
            backup_replication_id uniqueidentifier NOT NULL CONSTRAINT PK_backup_replications PRIMARY KEY,
            backup_verification_id uniqueidentifier NULL,
            destination_code varchar(60) NOT NULL,
            encrypted bit NOT NULL,
            destination_reference nvarchar(500) NOT NULL,
            source_sha256 char(64) NOT NULL,
            replicated_sha256 char(64) NULL,
            status varchar(20) NOT NULL,
            started_at_utc datetime2(3) NOT NULL CONSTRAINT DF_backup_replications_started DEFAULT SYSUTCDATETIME(),
            completed_at_utc datetime2(3) NULL,
            failure_code varchar(100) NULL,
            CONSTRAINT FK_backup_replications_verification FOREIGN KEY(backup_verification_id) REFERENCES app.backup_verifications(backup_verification_id),
            CONSTRAINT CK_backup_replications_status CHECK(status IN ('PENDING','COPIED','VERIFIED','FAILED')),
            CONSTRAINT CK_backup_replications_encrypted CHECK(encrypted=1)
        );
    END;

    COMMIT TRANSACTION;
    PRINT 'Aurex V4 artifact, security, event and retention migration completed.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
